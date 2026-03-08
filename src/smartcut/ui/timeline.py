from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from smartcut.editor.models import EditDecision

_MARGIN_LEFT = 50
_MARGIN_RIGHT = 10


def _score_to_color(score: float) -> QColor:
    """Map interest score [0,1] to red→yellow→green."""
    hue = int(min(max(score, 0.0), 1.0) * 120)
    return QColor.fromHsv(hue, 180, 210)


class TimelineWidget(QWidget):
    """Custom-painted timeline showing clips on the source video duration.

    Clips can be selected and dragged to change their source position.
    """

    clip_selected = Signal(int)  # index of selected clip (-1 for deselect)
    clip_moved = Signal(int, float, float)  # index, new_source_start, new_source_end

    RULER_HEIGHT = 28
    SECTION_HEIGHT = 0
    TRACK_HEIGHT = 44
    MIN_HEIGHT = RULER_HEIGHT + TRACK_HEIGHT + 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._clips: list[EditDecision] = []
        self._marks: list[float] = []
        self._video_duration = 0.0
        self._selected = -1
        self._cursor_time: float = -1.0

        # Drag state
        self._drag_index = -1
        self._drag_offset = 0.0

        self.setMinimumHeight(self.MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    def set_data(
        self,
        clips: list[EditDecision],
        video_duration: float,
    ):
        self._clips = list(clips)
        self._video_duration = video_duration
        self._selected = -1
        self._cursor_time = -1.0
        self.update()

    def set_cursor_position(self, seconds: float):
        self._cursor_time = seconds
        self.update()

    def set_marks(self, timestamps: list[float]):
        self._marks = list(timestamps)
        self.update()

    def select_clip(self, index: int):
        if 0 <= index < len(self._clips):
            self._selected = index
            self.clip_selected.emit(index)
            self.update()

    @property
    def clips(self) -> list[EditDecision]:
        return self._clips

    @property
    def selected_index(self) -> int:
        return self._selected

    # --- Coordinate mapping ---

    def _track_width(self) -> float:
        return max(1.0, self.width() - _MARGIN_LEFT - _MARGIN_RIGHT)

    def _time_to_x(self, t: float) -> float:
        if self._video_duration <= 0:
            return _MARGIN_LEFT
        return _MARGIN_LEFT + (t / self._video_duration) * self._track_width()

    def _x_to_time(self, x: float) -> float:
        if self._track_width() <= 0:
            return 0.0
        return max(0.0, (x - _MARGIN_LEFT) / self._track_width() * self._video_duration)

    # --- Painting ---

    def paintEvent(self, event):
        if self._video_duration <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self._draw_ruler(painter)
        self._draw_track(painter)
        self._draw_clips(painter)
        self._draw_marks(painter)
        self._draw_cursor(painter)

        painter.end()

    def _draw_ruler(self, p: QPainter):
        y = 0
        h = self.RULER_HEIGHT
        p.setPen(QPen(QColor("#888"), 1))
        p.setFont(QFont("monospace", 8))

        # Determine tick interval based on duration
        if self._video_duration <= 30:
            major, minor = 5.0, 1.0
        elif self._video_duration <= 120:
            major, minor = 15.0, 5.0
        elif self._video_duration <= 600:
            major, minor = 60.0, 15.0
        else:
            major, minor = 300.0, 60.0

        t = 0.0
        while t <= self._video_duration:
            x = self._time_to_x(t)
            is_major = (t % major) < 0.001 or (major - (t % major)) < 0.001
            if is_major:
                p.setPen(QPen(QColor("#aaa"), 1))
                p.drawLine(int(x), y + h - 14, int(x), y + h)
                m, s = divmod(int(t), 60)
                p.drawText(int(x) - 15, y + h - 16, f"{m}:{s:02d}")
            else:
                p.setPen(QPen(QColor("#555"), 1))
                p.drawLine(int(x), y + h - 6, int(x), y + h)
            t += minor

    def _draw_track(self, p: QPainter):
        y = self.RULER_HEIGHT + self.SECTION_HEIGHT
        h = self.TRACK_HEIGHT
        # Track background
        p.fillRect(
            QRectF(_MARGIN_LEFT, y, self._track_width(), h),
            QBrush(QColor("#1e1e1e")),
        )
        # Track border
        p.setPen(QPen(QColor("#444"), 1))
        p.drawRect(QRectF(_MARGIN_LEFT, y, self._track_width(), h))

    def _draw_clips(self, p: QPainter):
        y = self.RULER_HEIGHT + self.SECTION_HEIGHT + 4
        h = self.TRACK_HEIGHT - 8

        for i, clip in enumerate(self._clips):
            x1 = self._time_to_x(clip.source_start)
            x2 = self._time_to_x(clip.source_end)
            w = max(3.0, x2 - x1)

            color = _score_to_color(clip.interest_score)
            if i == self._selected:
                color = color.lighter(130)

            # Clip body
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(color))
            p.drawRoundedRect(QRectF(x1, y, w, h), 3, 3)

            # Clip border
            border_color = QColor("#ffffff") if i == self._selected else QColor("#888")
            border_width = 2 if i == self._selected else 1
            p.setPen(QPen(border_color, border_width))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(x1, y, w, h), 3, 3)

            # Clip index label
            if w > 20:
                p.setPen(QPen(QColor("#000"), 1))
                p.setFont(QFont("monospace", 7, QFont.Bold))
                p.drawText(QRectF(x1, y, w, h), Qt.AlignCenter, str(i + 1))

    def _draw_marks(self, p: QPainter):
        if not self._marks or self._video_duration <= 0:
            return
        pen = QPen(QColor("#ff5252"), 2, Qt.DashLine)
        p.setPen(pen)
        top = 0
        bottom = self.RULER_HEIGHT + self.SECTION_HEIGHT + self.TRACK_HEIGHT
        for t in self._marks:
            x = int(self._time_to_x(t))
            p.drawLine(x, top, x, bottom)

    def _draw_cursor(self, p: QPainter):
        if self._cursor_time < 0 or self._video_duration <= 0:
            return
        x = self._time_to_x(self._cursor_time)
        bottom = self.RULER_HEIGHT + self.SECTION_HEIGHT + self.TRACK_HEIGHT
        # Vertical line
        p.setPen(QPen(QColor("#42A5F5"), 2))
        p.drawLine(int(x), 0, int(x), bottom)
        # Inverted triangle playhead at top of ruler
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#42A5F5")))
        tri = QPolygonF([
            QPointF(x - 5, 0),
            QPointF(x + 5, 0),
            QPointF(x, 8),
        ])
        p.drawPolygon(tri)

    # --- Mouse interaction ---

    def _clip_at(self, x: float, y: float) -> int:
        """Return index of clip at (x, y) or -1."""
        track_y = self.RULER_HEIGHT + self.SECTION_HEIGHT + 4
        track_h = self.TRACK_HEIGHT - 8
        if not (track_y <= y <= track_y + track_h):
            return -1
        # Search in reverse so topmost clip gets priority
        for i in range(len(self._clips) - 1, -1, -1):
            clip = self._clips[i]
            x1 = self._time_to_x(clip.source_start)
            x2 = self._time_to_x(clip.source_end)
            if x1 <= x <= max(x2, x1 + 3):
                return i
        return -1

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        idx = self._clip_at(event.position().x(), event.position().y())
        self._selected = idx
        self.clip_selected.emit(idx)

        if idx >= 0:
            clip = self._clips[idx]
            click_time = self._x_to_time(event.position().x())
            self._drag_index = idx
            self._drag_offset = click_time - clip.source_start
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag_index < 0:
            # Update cursor
            idx = self._clip_at(event.position().x(), event.position().y())
            self.setCursor(Qt.OpenHandCursor if idx >= 0 else Qt.ArrowCursor)
            return

        self.setCursor(Qt.ClosedHandCursor)
        clip = self._clips[self._drag_index]
        clip_duration = clip.source_end - clip.source_start

        new_start = self._x_to_time(event.position().x()) - self._drag_offset
        new_start = max(0.0, min(new_start, self._video_duration - clip_duration))
        new_end = new_start + clip_duration

        self._clips[self._drag_index] = EditDecision(
            beat_index=clip.beat_index,
            source_start=new_start,
            source_end=new_end,
            target_start=clip.target_start,
            target_end=clip.target_end,
            interest_score=clip.interest_score,
        )
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_index >= 0:
            clip = self._clips[self._drag_index]
            self.clip_moved.emit(self._drag_index, clip.source_start, clip.source_end)
            self._drag_index = -1
        self.setCursor(Qt.ArrowCursor)
