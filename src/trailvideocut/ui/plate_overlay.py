"""Transparent overlay widget for displaying and editing plate bounding boxes."""

from __future__ import annotations

import sys

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from trailvideocut.plate.models import ClipPlateData, PlateBox

_HANDLE_SIZE = 8  # pixels
_MIN_BOX_PX = 10  # minimum box dimension in pixels


class PlateOverlayWidget(QWidget):
    """Overlay that draws plate bounding boxes on top of a QVideoWidget.

    Supports selecting, moving, resizing, deleting, and adding boxes.
    All PlateBox coordinates are normalized (0-1) relative to the video frame.
    """

    box_changed = Signal()  # emitted when any box is modified/added/deleted
    selection_changed = Signal()  # emitted when selected box changes
    unexpectedly_hidden = Signal()  # emitted when WM hides the overlay
    add_plate_requested = Signal(float, float)  # right-click norm (x, y)

    def __init__(self, parent=None):
        # Top-level frameless translucent window so it floats above
        # QVideoWidget's native Direct3D/OpenGL surface on Windows.
        super().__init__(None)
        self._logical_parent = parent
        flags = (
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        if sys.platform != "win32":
            # On non-Windows, owner-window trick isn't available; fall back.
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)

        self._clip_data: ClipPlateData | None = None
        self._current_frame: int = -1
        self._video_width: int = 1920
        self._video_height: int = 1080

        self._owner_set: bool = False
        self._selected_idx: int = -1  # index into current frame's box list
        self._dragging: bool = False
        self._resizing: bool = False
        self._resize_handle: str = ""  # e.g. "tl", "tr", "bl", "br", "t", "b", "l", "r"
        self._drag_start: QPointF = QPointF()
        self._drag_box_start: tuple[float, float, float, float] = (0, 0, 0, 0)
        self._hiding_programmatically: bool = False

        # Blur preview tiles: list of (norm_rect, QPixmap)
        self._blur_tiles: list[tuple[tuple[float, float, float, float], QPixmap]] = []

        # Zoom/pan state
        self._effective_video_rect: QRectF | None = None
        self._zoom_level: float = 1.0
        self._panning: bool = False
        self._pan_start: QPointF = QPointF()
        self._pan_started: bool = False
        self._deferred_deselect: bool = False

    # --- Visibility tracking ---

    def setVisible(self, visible: bool):
        if not visible:
            self._hiding_programmatically = True
        super().setVisible(visible)
        self._hiding_programmatically = False

    def hideEvent(self, event):
        super().hideEvent(event)
        if not self._hiding_programmatically:
            self.unexpectedly_hidden.emit()

    # --- Window ownership (Windows only) ---

    def showEvent(self, event):
        super().showEvent(event)
        if not self._owner_set:
            self._owner_set = True
            self._set_owner_window()

    def _set_owner_window(self):
        """Set this overlay as owned by the main application window (Windows only).

        An owned window stays above its owner but not above other applications.
        """
        if sys.platform != "win32":
            return

        import ctypes
        from ctypes import wintypes

        app = QApplication.instance()
        if app is None:
            return

        main_windows = [
            w for w in app.topLevelWidgets()
            if w.isWindow() and w is not self
            and not isinstance(w, PlateOverlayWidget)
        ]
        if not main_windows:
            return

        owner_hwnd = int(main_windows[0].winId())
        overlay_hwnd = int(self.winId())
        if not owner_hwnd or not overlay_hwnd:
            return

        GWL_HWNDPARENT = -8
        LONG_PTR = ctypes.c_ssize_t
        SetWindowLongPtrW = ctypes.windll.user32.SetWindowLongPtrW
        SetWindowLongPtrW.argtypes = [
            wintypes.HWND, ctypes.c_int, LONG_PTR,
        ]
        SetWindowLongPtrW.restype = LONG_PTR
        SetWindowLongPtrW(overlay_hwnd, GWL_HWNDPARENT, owner_hwnd)

    # --- Public API ---

    def set_video_size(self, width: int, height: int):
        self._video_width = max(1, width)
        self._video_height = max(1, height)
        self.update()

    def set_clip_data(self, data: ClipPlateData | None):
        self._clip_data = data
        old_idx = self._selected_idx
        self._selected_idx = -1
        if old_idx != -1:
            self.selection_changed.emit()
        self.update()

    def set_current_frame(self, frame_number: int, *, force: bool = False):
        if force or frame_number != self._current_frame:
            self._current_frame = frame_number
            old_idx = self._selected_idx
            self._selected_idx = -1
            if old_idx != -1:
                self.selection_changed.emit()
            self.update()

    def selected_box(self) -> PlateBox | None:
        boxes = self._current_boxes()
        if 0 <= self._selected_idx < len(boxes):
            return boxes[self._selected_idx]
        return None

    def select_box(self, idx: int):
        """Programmatically select a box by index without emitting selection_changed."""
        boxes = self._current_boxes()
        if 0 <= idx < len(boxes):
            if self._selected_idx != idx:
                self._selected_idx = idx
                self.update()
        elif idx < 0:
            if self._selected_idx != -1:
                self._selected_idx = -1
                self.update()

    def add_box(self, box: PlateBox):
        """Add a box to the current frame and select it."""
        if self._clip_data is None or self._current_frame < 0:
            return
        if self._current_frame not in self._clip_data.detections:
            self._clip_data.detections[self._current_frame] = []
        self._clip_data.detections[self._current_frame].append(box)
        self._selected_idx = len(self._clip_data.detections[self._current_frame]) - 1
        self.selection_changed.emit()
        self.box_changed.emit()
        self.update()

    def delete_selected(self):
        """Remove the currently selected box."""
        boxes = self._current_boxes()
        if 0 <= self._selected_idx < len(boxes):
            boxes.pop(self._selected_idx)
            if not boxes and self._current_frame in self._clip_data.detections:
                del self._clip_data.detections[self._current_frame]
            self._selected_idx = -1
            self.selection_changed.emit()
            self.box_changed.emit()
            self.update()

    def find_nearest_reference_box(self) -> PlateBox | None:
        """Find the nearest plate box from any frame (prior preferred, then next)."""
        if self._clip_data is None:
            return None
        # Search backward first
        for frame in sorted(self._clip_data.detections.keys(), reverse=True):
            if frame < self._current_frame:
                boxes = self._clip_data.detections[frame]
                if boxes:
                    return boxes[0]
        # No prior frame — search forward
        for frame in sorted(self._clip_data.detections.keys()):
            if frame > self._current_frame:
                boxes = self._clip_data.detections[frame]
                if boxes:
                    return boxes[0]
        return None

    def get_last_mouse_norm_pos(self) -> tuple[float, float] | None:
        """Return the last known mouse position in normalized video coordinates, or None."""
        pos = self.mapFromGlobal(QCursor.pos())
        vr = self._video_rect()
        if vr.isEmpty() or vr.width() == 0 or vr.height() == 0:
            return None
        nx = (pos.x() - vr.x()) / vr.width()
        ny = (pos.y() - vr.y()) / vr.height()
        if 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0:
            return (nx, ny)
        return None

    def set_effective_video_rect(self, rect: QRectF | None):
        """Override the video rect with an effective rect from the zoomed/panned view.

        When set, _video_rect() uses this instead of computing from aspect ratio.
        The rect is in this overlay widget's coordinate space and may extend beyond
        widget bounds when zoomed in.
        """
        self._effective_video_rect = rect
        self.update()

    def set_zoom(self, zoom: float):
        """Inform the overlay of the current zoom level (for pan gesture)."""
        self._zoom_level = zoom

    def set_blur_tiles(
        self,
        tiles: list[tuple[tuple[float, float, float, float], QPixmap]],
    ):
        """Set blurred plate pixmap tiles for preview rendering.

        Each entry is ``((nx, ny, nw, nh), pixmap)``.
        """
        self._blur_tiles = tiles
        self.update()

    def clear_blur_tiles(self):
        """Remove all blur preview tiles."""
        if self._blur_tiles:
            self._blur_tiles.clear()
            self.update()

    # --- Coordinate mapping ---

    def _video_rect(self) -> QRectF:
        """Compute the actual video display rect within the widget, respecting aspect ratio.

        If an effective rect has been set (due to zoom/pan), use that instead.
        """
        if self._effective_video_rect is not None:
            return self._effective_video_rect

        widget_w = self.width()
        widget_h = self.height()
        video_ar = self._video_width / self._video_height
        widget_ar = widget_w / widget_h

        if widget_ar > video_ar:
            # Pillarbox: video is narrower
            display_h = widget_h
            display_w = display_h * video_ar
            x = (widget_w - display_w) / 2
            y = 0
        else:
            # Letterbox: video is wider
            display_w = widget_w
            display_h = display_w / video_ar
            x = 0
            y = (widget_h - display_h) / 2

        return QRectF(x, y, display_w, display_h)

    def _norm_to_widget(self, nx: float, ny: float, nw: float, nh: float) -> QRectF:
        """Convert normalized box to widget pixel rect."""
        vr = self._video_rect()
        return QRectF(
            vr.x() + nx * vr.width(),
            vr.y() + ny * vr.height(),
            nw * vr.width(),
            nh * vr.height(),
        )

    def _widget_to_norm(self, px: float, py: float) -> tuple[float, float]:
        """Convert widget pixel position to normalized video coords."""
        vr = self._video_rect()
        nx = (px - vr.x()) / vr.width()
        ny = (py - vr.y()) / vr.height()
        return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))

    def _current_boxes(self) -> list[PlateBox]:
        if self._clip_data is None or self._current_frame < 0:
            return []
        return self._clip_data.detections.get(self._current_frame, [])

    # --- Paint ---

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Fill video area with near-invisible color (alpha=1) so clicks on
        # "empty" areas are captured by this window instead of falling through
        # to the underlying window (X11/Wayland click-through behaviour on
        # fully transparent pixels).
        vr = self._video_rect()
        painter.fillRect(vr, QColor(0, 0, 0, 1))

        # Draw blur preview tiles (before boxes so borders are visible on top)
        for (nx, ny, nw, nh), pixmap in self._blur_tiles:
            target = self._norm_to_widget(nx, ny, nw, nh)
            painter.drawPixmap(target.toRect(), pixmap)

        boxes = self._current_boxes()
        if not boxes:
            painter.end()
            return

        label_font = QFont()
        label_font.setPixelSize(10)

        for i, box in enumerate(boxes):
            rect = self._norm_to_widget(box.x, box.y, box.w, box.h)
            selected = i == self._selected_idx

            # Fill (skip if blur tiles are shown — the pixmap replaces the fill)
            if not self._blur_tiles:
                fill_color = QColor(0, 150, 255, 50) if not selected else QColor(255, 200, 0, 70)
                painter.setBrush(QBrush(fill_color))
            else:
                painter.setBrush(Qt.NoBrush)

            # Border
            if selected:
                pen = QPen(QColor(255, 200, 0), 2, Qt.SolidLine)
            elif box.manual:
                pen = QPen(QColor(0, 200, 100), 2, Qt.DashLine)
            else:
                pen = QPen(QColor(0, 150, 255), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect)

            # Blur % label for non-default blur_strength
            if box.blur_strength < 0.99:
                pct = f"{int(box.blur_strength * 100)}%"
                painter.setFont(label_font)
                # Background pill
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(pct) + 6
                th = fm.height() + 2
                lx = rect.right() - tw - 2
                ly = rect.top() + 2
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 160))
                painter.drawRoundedRect(QRectF(lx, ly, tw, th), 3, 3)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(QRectF(lx, ly, tw, th), Qt.AlignCenter, pct)

            # Resize handles for selected box
            if selected:
                self._draw_handles(painter, rect)

        painter.end()

    def _draw_handles(self, painter: QPainter, rect: QRectF):
        painter.setBrush(QBrush(QColor(255, 200, 0)))
        painter.setPen(QPen(QColor(80, 80, 80), 1))
        hs = _HANDLE_SIZE
        hh = hs / 2

        positions = self._handle_positions(rect)
        for pos in positions.values():
            painter.drawRect(QRectF(pos.x() - hh, pos.y() - hh, hs, hs))

    def _handle_positions(self, rect: QRectF) -> dict[str, QPointF]:
        cx = rect.center().x()
        cy = rect.center().y()
        return {
            "tl": rect.topLeft(),
            "tr": rect.topRight(),
            "bl": rect.bottomLeft(),
            "br": rect.bottomRight(),
            "t": QPointF(cx, rect.top()),
            "b": QPointF(cx, rect.bottom()),
            "l": QPointF(rect.left(), cy),
            "r": QPointF(rect.right(), cy),
        }

    def _forward_focus(self):
        """Activate main window and move focus to logical parent so keyboard shortcuts work."""
        if self._logical_parent is not None:
            top = self._logical_parent.window()
            if top is not None:
                top.activateWindow()
            self._logical_parent.setFocus()

    # --- Mouse events ---

    def _handle_right_click(self, event):
        """Right-click: delete selected plate, or request add if none selected."""
        if self._dragging or self._resizing or self._panning:
            event.accept()
            return
        if self._selected_idx >= 0:
            self.delete_selected()
        else:
            nx, ny = self._widget_to_norm(event.position().x(), event.position().y())
            self.add_plate_requested.emit(nx, ny)
        event.accept()
        self._forward_focus()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._handle_right_click(event)
            return
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position()
        boxes = self._current_boxes()

        # Check resize handles on selected box first
        if 0 <= self._selected_idx < len(boxes):
            box = boxes[self._selected_idx]
            rect = self._norm_to_widget(box.x, box.y, box.w, box.h)
            handle = self._hit_handle(pos, rect)
            if handle:
                self._resizing = True
                self._resize_handle = handle
                self._drag_start = pos
                self._drag_box_start = (box.x, box.y, box.w, box.h)
                event.accept()
                self._forward_focus()
                return

        # Hit test boxes (smallest area wins)
        hit = -1
        hit_area = float("inf")
        for i, box in enumerate(boxes):
            rect = self._norm_to_widget(box.x, box.y, box.w, box.h)
            if rect.contains(pos):
                area = rect.width() * rect.height()
                if area < hit_area:
                    hit = i
                    hit_area = area

        if hit >= 0:
            old_idx = self._selected_idx
            self._selected_idx = hit
            box = boxes[hit]
            self._dragging = True
            self._drag_start = pos
            self._drag_box_start = (box.x, box.y, box.w, box.h)
            if old_idx != hit:
                self.selection_changed.emit()
            self.update()
            event.accept()
        elif self._zoom_level > 1.0:
            # Empty space click while zoomed — start potential pan
            self._panning = True
            self._pan_started = False
            self._pan_start = pos
            self._deferred_deselect = self._selected_idx >= 0
            event.accept()
        else:
            # Empty space click, not zoomed — deselect immediately
            old_idx = self._selected_idx
            self._selected_idx = -1
            if old_idx != -1:
                self.selection_changed.emit()
            self.update()
            event.accept()

        self._forward_focus()

    def mouseMoveEvent(self, event):
        pos = event.position()
        boxes = self._current_boxes()

        if self._panning:
            dx = pos.x() - self._pan_start.x()
            dy = pos.y() - self._pan_start.y()
            if not self._pan_started:
                if abs(dx) > 3 or abs(dy) > 3:
                    self._pan_started = True
                    self._deferred_deselect = False  # real drag, not a click
            if self._pan_started and self._logical_parent is not None:
                self._pan_start = pos
                self._logical_parent.pan_video(int(dx), int(dy))
            event.accept()
            return

        if self._dragging and 0 <= self._selected_idx < len(boxes):
            box = boxes[self._selected_idx]
            vr = self._video_rect()
            dx = (pos.x() - self._drag_start.x()) / vr.width()
            dy = (pos.y() - self._drag_start.y()) / vr.height()

            ox, oy, ow, oh = self._drag_box_start
            new_x = max(0.0, min(1.0 - ow, ox + dx))
            new_y = max(0.0, min(1.0 - oh, oy + dy))

            box.x = new_x
            box.y = new_y
            self.update()

        elif self._resizing and 0 <= self._selected_idx < len(boxes):
            self._apply_resize(pos, boxes[self._selected_idx])
            self.update()

        else:
            # Update cursor shape based on hover
            self._update_cursor(pos)

        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._panning:
                if not self._pan_started and self._deferred_deselect:
                    # Was a click (not drag) on empty space while zoomed — deselect
                    old_idx = self._selected_idx
                    self._selected_idx = -1
                    if old_idx != -1:
                        self.selection_changed.emit()
                    self.update()
                self._panning = False
                self._pan_started = False
                self._deferred_deselect = False
            elif self._dragging or self._resizing:
                self.box_changed.emit()
            self._dragging = False
            self._resizing = False
            self._resize_handle = ""
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._logical_parent is not None:
            QApplication.sendEvent(self._logical_parent, event)
        else:
            super().wheelEvent(event)

    # --- Resize logic ---

    def _hit_handle(self, pos: QPointF, rect: QRectF) -> str:
        positions = self._handle_positions(rect)
        for name, hpos in positions.items():
            if abs(pos.x() - hpos.x()) <= _HANDLE_SIZE and abs(pos.y() - hpos.y()) <= _HANDLE_SIZE:
                return name
        return ""

    def _apply_resize(self, pos: QPointF, box: PlateBox):
        vr = self._video_rect()
        ox, oy, ow, oh = self._drag_box_start
        dx = (pos.x() - self._drag_start.x()) / vr.width()
        dy = (pos.y() - self._drag_start.y()) / vr.height()

        min_w = _MIN_BOX_PX / max(1, vr.width())
        min_h = _MIN_BOX_PX / max(1, vr.height())

        h = self._resize_handle
        new_x, new_y, new_w, new_h = ox, oy, ow, oh

        if "l" in h:
            new_x = max(0.0, ox + dx)
            new_w = max(min_w, ow - dx)
            if ox + dx < 0:
                new_x = 0.0
                new_w = ox + ow
        if "r" in h:
            new_w = max(min_w, ow + dx)
            if new_x + new_w > 1.0:
                new_w = 1.0 - new_x
        if "t" in h:
            new_y = max(0.0, oy + dy)
            new_h = max(min_h, oh - dy)
            if oy + dy < 0:
                new_y = 0.0
                new_h = oy + oh
        if "b" in h:
            new_h = max(min_h, oh + dy)
            if new_y + new_h > 1.0:
                new_h = 1.0 - new_y

        box.x = new_x
        box.y = new_y
        box.w = new_w
        box.h = new_h

    def _update_cursor(self, pos: QPointF):
        boxes = self._current_boxes()
        if 0 <= self._selected_idx < len(boxes):
            box = boxes[self._selected_idx]
            rect = self._norm_to_widget(box.x, box.y, box.w, box.h)
            handle = self._hit_handle(pos, rect)
            if handle in ("tl", "br"):
                self.setCursor(QCursor(Qt.SizeFDiagCursor))
                return
            if handle in ("tr", "bl"):
                self.setCursor(QCursor(Qt.SizeBDiagCursor))
                return
            if handle in ("t", "b"):
                self.setCursor(QCursor(Qt.SizeVerCursor))
                return
            if handle in ("l", "r"):
                self.setCursor(QCursor(Qt.SizeHorCursor))
                return
            if rect.contains(pos):
                self.setCursor(QCursor(Qt.SizeAllCursor))
                return

        # Check if hovering over any box
        for box in boxes:
            rect = self._norm_to_widget(box.x, box.y, box.w, box.h)
            if rect.contains(pos):
                self.setCursor(QCursor(Qt.PointingHandCursor))
                return

        # Show grab cursor when zoomed (indicating pan is available)
        if self._zoom_level > 1.0:
            self.setCursor(QCursor(Qt.OpenHandCursor))
            return

        self.setCursor(QCursor(Qt.ArrowCursor))
