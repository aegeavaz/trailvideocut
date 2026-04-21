"""Transparent overlay widget for displaying and editing plate bounding boxes."""

from __future__ import annotations

import math
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication, QWidget

from trailvideocut.plate.models import ClipPlateData, PlateBox

_HANDLE_SIZE = 8  # pixels
_MIN_BOX_PX = 10  # minimum box dimension in pixels
_ROTATE_HANDLE_OFFSET_PX = 18  # distance above top edge where the rotate handle sits


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
        self._rotating: bool = False
        self._resize_handle: str = ""  # "tl","tr","bl","br","t","b","l","r","rotate"
        self._drag_start: QPointF = QPointF()
        # Drag-start snapshot: (centre_x, centre_y, w, h, angle) in norm coords.
        self._drag_box_start: tuple[float, float, float, float, float] = (0, 0, 0, 0, 0)
        # For the rotate handle: mouse angle (degrees) from box centre at
        # drag start, so we can delta-rotate as the user drags.
        self._rotate_start_mouse_angle: float = 0.0
        self._hiding_programmatically: bool = False

        # Blur preview tiles: list of (norm_rect, QPixmap)
        self._blur_tiles: list[tuple[tuple[float, float, float, float], QPixmap]] = []

        # Phone-filter debug zones: normalized (x, y, w, h) rects drawn as
        # read-only debug geometry; never participate in hit-testing.
        self._phone_zones: list[tuple[float, float, float, float]] = []
        self._phone_zones_visible: bool = False

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

    # --- Phone-filter debug zones ---

    def set_phone_zones(
        self,
        zones: list[tuple[float, float, float, float]],
    ):
        """Set the phone-filter exclusion zones to draw for the current frame.

        Each zone is a normalized ``(x, y, w, h)`` tuple. Passing an empty
        list clears the zones. The overlay repaints only when the value
        actually changes.
        """
        new_zones = list(zones)
        if new_zones != self._phone_zones:
            self._phone_zones = new_zones
            self.update()

    def clear_phone_zones(self):
        """Remove all phone-filter debug zones for the current frame."""
        if self._phone_zones:
            self._phone_zones = []
            self.update()

    def set_phone_zones_visible(self, visible: bool):
        """Toggle whether phone-filter debug zones are drawn. Independent of
        plate-box visibility.
        """
        v = bool(visible)
        if v != self._phone_zones_visible:
            self._phone_zones_visible = v
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

    def _oriented_corners_widget(self, box: PlateBox) -> list[QPointF]:
        """Return the four corners of *box* as widget-pixel ``QPointF`` in
        TL, TR, BR, BL order (of the plate-aligned rectangle, before rotation).

        Rotation is computed in video-pixel space (not in a normalized 1x1
        space). The single helper keeps the outline renderer and the handle
        anchor points fed from the same geometry, so they cannot drift.
        """
        vr = self._video_rect()
        corners = box.corners_px(vr.width(), vr.height())
        return [
            QPointF(vr.x() + x, vr.y() + y) for x, y in corners
        ]

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

        # Draw phone-filter debug zones first so blur tiles and plate boxes
        # layer on top of them. Zones are non-interactive debug geometry.
        if self._phone_zones_visible and self._phone_zones:
            zone_pen = QPen(QColor(0xE0, 0x40, 0xFB), 2, Qt.DashLine)
            zone_fill = QColor(0xE0, 0x40, 0xFB, 30)
            painter.setPen(zone_pen)
            painter.setBrush(QBrush(zone_fill))
            for nx, ny, nw, nh in self._phone_zones:
                painter.drawRect(self._norm_to_widget(nx, ny, nw, nh))

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
            # The envelope rect drives handles and hit-tests for both the
            # axis-aligned and the oriented cases.
            env_x, env_y, env_w, env_h = box.aabb_envelope()
            rect = self._norm_to_widget(env_x, env_y, env_w, env_h)
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

            if box.angle == 0.0:
                painter.drawRect(rect)
            else:
                poly = QPolygonF(self._oriented_corners_widget(box))
                painter.drawPolygon(poly)

            # Resize + rotate handles for selected box — on the rotated rect.
            if selected:
                self._draw_handles(painter, box)

        painter.end()

    def _draw_handles(self, painter: QPainter, box: PlateBox):
        painter.setBrush(QBrush(QColor(255, 200, 0)))
        painter.setPen(QPen(QColor(80, 80, 80), 1))
        hs = _HANDLE_SIZE
        hh = hs / 2

        positions = self._handle_positions_for_box(box)
        for name, pos in positions.items():
            if name == "rotate":
                # Rotation handle: circle, not square, and drawn with a short
                # line connecting it to the top edge for affordance.
                top = positions["t"]
                painter.drawLine(top, pos)
                painter.drawEllipse(pos, hh, hh)
            else:
                painter.drawRect(QRectF(pos.x() - hh, pos.y() - hh, hs, hs))

    def _handle_positions_for_box(
        self, box: PlateBox,
    ) -> dict[str, QPointF]:
        """Return handle positions on the (possibly rotated) plate-aligned
        rectangle. For axis-aligned boxes (``angle == 0``) the positions
        coincide with the AABB corners + edge midpoints.
        """
        tl, tr, br, bl = self._oriented_corners_widget(box)

        def _mid(a: QPointF, b: QPointF) -> QPointF:
            return QPointF((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0)

        t = _mid(tl, tr)
        b_mid = _mid(bl, br)
        left = _mid(tl, bl)
        right = _mid(tr, br)
        centre = _mid(tl, br)

        # Rotation handle sits ``_ROTATE_HANDLE_OFFSET_PX`` away from the top
        # edge along the box's local "up" direction.
        up_x = t.x() - centre.x()
        up_y = t.y() - centre.y()
        up_len = math.hypot(up_x, up_y)
        if up_len > 0:
            rot = QPointF(
                t.x() + up_x / up_len * _ROTATE_HANDLE_OFFSET_PX,
                t.y() + up_y / up_len * _ROTATE_HANDLE_OFFSET_PX,
            )
        else:
            rot = QPointF(t.x(), t.y() - _ROTATE_HANDLE_OFFSET_PX)

        return {
            "tl": tl, "tr": tr, "br": br, "bl": bl,
            "t": t, "b": b_mid, "l": left, "r": right,
            "rotate": rot,
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

        # Check resize/rotate handles on selected box first — handles live on
        # the rotated plate-aligned rect.
        if 0 <= self._selected_idx < len(boxes):
            box = boxes[self._selected_idx]
            handle = self._hit_handle(pos, box)
            if handle:
                self._resize_handle = handle
                self._drag_start = pos
                # Capture full rotation-preserving state at drag start:
                # centre in normalized coords + plate-aligned (w, h, angle).
                cx = box.x + box.w / 2.0
                cy = box.y + box.h / 2.0
                self._drag_box_start = (cx, cy, box.w, box.h, box.angle)
                if handle == "rotate":
                    self._rotating = True
                    vr = self._video_rect()
                    centre_widget_x = vr.x() + cx * vr.width()
                    centre_widget_y = vr.y() + cy * vr.height()
                    self._rotate_start_mouse_angle = math.degrees(math.atan2(
                        pos.y() - centre_widget_y,
                        pos.x() - centre_widget_x,
                    ))
                else:
                    self._resizing = True
                event.accept()
                self._forward_focus()
                return

        # Hit test boxes (smallest area wins) — test containment against the
        # rotated rect so clicks near oriented corners hit the box.
        hit = -1
        hit_area = float("inf")
        for i, box in enumerate(boxes):
            if self._point_in_box(pos, box):
                # Use plate-aligned area (not envelope) so tie-break picks the
                # smallest actual box.
                area = box.w * box.h
                if area < hit_area:
                    hit = i
                    hit_area = area

        if hit >= 0:
            old_idx = self._selected_idx
            self._selected_idx = hit
            box = boxes[hit]
            self._dragging = True
            self._drag_start = pos
            cx = box.x + box.w / 2.0
            cy = box.y + box.h / 2.0
            self._drag_box_start = (cx, cy, box.w, box.h, box.angle)
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

            # Move preserves rotation and plate-aligned dimensions; only the
            # centre shifts.
            ocx, ocy, ow, oh, oangle = self._drag_box_start
            new_cx = ocx + dx
            new_cy = ocy + dy
            # Clamp so the AABB envelope stays inside the frame.
            tmp = PlateBox(
                x=new_cx - ow / 2, y=new_cy - oh / 2,
                w=ow, h=oh, angle=oangle,
            )
            ex, ey, ew, eh = tmp.aabb_envelope()
            if ex < 0:
                new_cx -= ex
            if ey < 0:
                new_cy -= ey
            if ex + ew > 1:
                new_cx -= (ex + ew - 1)
            if ey + eh > 1:
                new_cy -= (ey + eh - 1)

            box.x = new_cx - ow / 2
            box.y = new_cy - oh / 2
            box.w = ow
            box.h = oh
            box.angle = oangle
            self.update()

        elif self._rotating and 0 <= self._selected_idx < len(boxes):
            self._apply_rotate(pos, boxes[self._selected_idx])
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
            elif self._dragging or self._resizing or self._rotating:
                self.box_changed.emit()
            self._dragging = False
            self._resizing = False
            self._rotating = False
            self._resize_handle = ""
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._logical_parent is not None:
            QApplication.sendEvent(self._logical_parent, event)
        else:
            super().wheelEvent(event)

    # --- Hit testing / resize / rotate ---

    def _hit_handle(self, pos: QPointF, box: PlateBox) -> str:
        """Return the name of the handle under *pos* (``""`` if none)."""
        positions = self._handle_positions_for_box(box)
        best = ""
        best_dist = float("inf")
        for name, hpos in positions.items():
            dx = pos.x() - hpos.x()
            dy = pos.y() - hpos.y()
            # Rotation handle is a circle, use radial test. Others use a
            # generous square hit region.
            if name == "rotate":
                if math.hypot(dx, dy) <= _HANDLE_SIZE:
                    dist = math.hypot(dx, dy)
                    if dist < best_dist:
                        best, best_dist = name, dist
            else:
                if abs(dx) <= _HANDLE_SIZE and abs(dy) <= _HANDLE_SIZE:
                    dist = math.hypot(dx, dy)
                    if dist < best_dist:
                        best, best_dist = name, dist
        return best

    def _point_in_box(self, pos: QPointF, box: PlateBox) -> bool:
        """Return True if the widget-coord point *pos* lies inside the
        (possibly rotated) plate-aligned rectangle of *box*.

        Hit-test math lives in video-pixel space so non-square videos do not
        distort the rotation.
        """
        vr = self._video_rect()
        if vr.width() <= 0 or vr.height() <= 0:
            return False
        cx_px = vr.x() + (box.x + box.w / 2.0) * vr.width()
        cy_px = vr.y() + (box.y + box.h / 2.0) * vr.height()
        dx = pos.x() - cx_px
        dy = pos.y() - cy_px
        rad = math.radians(-box.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        local_x = dx * cos_a - dy * sin_a
        local_y = dx * sin_a + dy * cos_a
        half_w_px = box.w * vr.width() / 2.0
        half_h_px = box.h * vr.height() / 2.0
        return abs(local_x) <= half_w_px and abs(local_y) <= half_h_px

    def _apply_rotate(self, pos: QPointF, box: PlateBox):
        """Rotation-handle drag: rotate the box so the rotation handle
        follows the mouse angle, anchored around the box centre."""
        vr = self._video_rect()
        ocx, ocy, ow, oh, oangle = self._drag_box_start
        centre_widget_x = vr.x() + ocx * vr.width()
        centre_widget_y = vr.y() + ocy * vr.height()
        mouse_angle = math.degrees(math.atan2(
            pos.y() - centre_widget_y,
            pos.x() - centre_widget_x,
        ))
        delta = mouse_angle - self._rotate_start_mouse_angle
        box.x = ocx - ow / 2
        box.y = ocy - oh / 2
        box.w = ow
        box.h = oh
        box.angle = oangle + delta

    def _apply_resize(self, pos: QPointF, box: PlateBox):
        """Resize that preserves rotation. The handle's opposite reference
        (corner or edge) stays fixed in widget coordinates; the new
        plate-aligned ``(w, h)`` are computed by projecting the mouse offset
        from that reference onto the box's local axes **in pixel space**,
        then converted back to normalized coordinates. Doing the projection
        in pixel space is what keeps oriented boxes as rectangles on
        non-square videos.
        """
        vr = self._video_rect()
        vw = max(1.0, vr.width())
        vh = max(1.0, vr.height())
        ocx, ocy, ow, oh, oangle = self._drag_box_start

        # Original centre + extents in pixel space.
        ocx_px = ocx * vw
        ocy_px = ocy * vh
        ow_px = ow * vw
        oh_px = oh * vh

        # Plate's local axes as proper unit vectors in pixel space.
        rad = math.radians(oangle)
        ux, uy = math.cos(rad), math.sin(rad)          # plate-horizontal
        vx, vy = -math.sin(rad), math.cos(rad)          # plate-vertical

        # Mouse in video-pixel coords.
        mouse_x = pos.x() - vr.x()
        mouse_y = pos.y() - vr.y()

        # Fixed reference in plate-local multiples of (ow_px/2, oh_px/2).
        ref_plate = {
            "l":  (+1,  0),
            "r":  (-1,  0),
            "t":  ( 0, +1),
            "b":  ( 0, -1),
            "tl": (+1, +1),
            "tr": (-1, +1),
            "bl": (+1, -1),
            "br": (-1, -1),
        }.get(self._resize_handle, (0, 0))
        ref_u, ref_v = ref_plate

        # Fixed reference point in video-pixel coords.
        ref_x_px = ocx_px + ref_u * (ow_px / 2) * ux + ref_v * (oh_px / 2) * vx
        ref_y_px = ocy_px + ref_u * (ow_px / 2) * uy + ref_v * (oh_px / 2) * vy

        # Project the reference→mouse vector onto the plate's local axes.
        rx = mouse_x - ref_x_px
        ry = mouse_y - ref_y_px
        proj_u = rx * ux + ry * uy     # plate-horizontal pixels from ref
        proj_v = rx * vx + ry * vy     # plate-vertical

        handle = self._resize_handle
        new_w_px = ow_px
        new_h_px = oh_px
        if handle in ("l", "r", "tl", "tr", "bl", "br"):
            new_w_px = max(_MIN_BOX_PX, abs(proj_u))
        if handle in ("t", "b", "tl", "tr", "bl", "br"):
            new_h_px = max(_MIN_BOX_PX, abs(proj_v))

        # New centre: half-extents away from the reference along local axes.
        # Sign flips because ref_u = +1 means the reference sits at the
        # +u side and the centre is toward -u.
        cu = (new_w_px / 2) * (1 if ref_u <= 0 else -1) if handle in (
            "l", "r", "tl", "tr", "bl", "br"
        ) else (ow_px / 2) * (1 if ref_u <= 0 else -1)
        cv = (new_h_px / 2) * (1 if ref_v <= 0 else -1) if handle in (
            "t", "b", "tl", "tr", "bl", "br"
        ) else (oh_px / 2) * (1 if ref_v <= 0 else -1)
        # Edge handles leave the non-moving axis at its original centre.
        if handle in ("l", "r"):
            cv = 0
        if handle in ("t", "b"):
            cu = 0

        new_cx_px = ref_x_px + cu * ux + cv * vx
        new_cy_px = ref_y_px + cu * uy + cv * vy

        new_w = new_w_px / vw
        new_h = new_h_px / vh
        new_cx = new_cx_px / vw
        new_cy = new_cy_px / vh

        box.x = new_cx - new_w / 2
        box.y = new_cy - new_h / 2
        box.w = new_w
        box.h = new_h
        box.angle = oangle

    def _update_cursor(self, pos: QPointF):
        boxes = self._current_boxes()
        if 0 <= self._selected_idx < len(boxes):
            box = boxes[self._selected_idx]
            handle = self._hit_handle(pos, box)
            if handle == "rotate":
                self.setCursor(QCursor(Qt.CrossCursor))
                return
            # For oriented boxes the diagonal/vertical/horizontal cursors no
            # longer map cleanly onto the widget axes, so use a single
            # "size all" cursor for any handle hover when rotated. For
            # angle == 0 we preserve the specific cursor per handle.
            if box.angle == 0.0:
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
            elif handle:
                self.setCursor(QCursor(Qt.SizeAllCursor))
                return
            if self._point_in_box(pos, box):
                self.setCursor(QCursor(Qt.SizeAllCursor))
                return

        # Check if hovering over any box (rotation-aware).
        for box in boxes:
            if self._point_in_box(pos, box):
                self.setCursor(QCursor(Qt.PointingHandCursor))
                return

        # Show grab cursor when zoomed (indicating pan is available)
        if self._zoom_level > 1.0:
            self.setCursor(QCursor(Qt.OpenHandCursor))
            return

        self.setCursor(QCursor(Qt.ArrowCursor))
