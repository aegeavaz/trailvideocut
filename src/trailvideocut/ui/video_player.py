from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)


class ClickSlider(QSlider):
    """QSlider that jumps to click position and paints mark indicators."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._marks: list[float] = []  # normalized 0-1 positions

    def set_marks(self, timestamps: list[float], duration: float):
        if duration > 0:
            self._marks = [t / duration for t in timestamps if 0 <= t <= duration]
        else:
            self._marks = []
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                int(event.position().x()), self.width(),
            )
            self.setValue(val)
            self.sliderMoved.emit(val)
            event.accept()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._marks:
            return
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self,
        )
        handle_len = self.style().pixelMetric(QStyle.PM_SliderLength, opt, self)
        available = groove.width() - handle_len
        offset = groove.left() + handle_len // 2

        painter = QPainter(self)
        pen = QPen(QColor("#ff5252"), 2)
        painter.setPen(pen)
        for norm in self._marks:
            x = offset + int(norm * available)
            painter.drawLine(x, 0, x, self.height())
        painter.end()


class VideoPlayer(QWidget):
    """QMediaPlayer-based video player with audio support."""

    position_changed = Signal(float)  # current time in seconds
    user_seeked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)

        self._duration_ms = 0
        self._fps = 30.0  # overwritten with real source FPS in load_video()
        self._want_play = False  # desired play/pause state (user intent)
        self._seeking = False
        self._on_transport: callable | None = None
        self._external_control: bool = False

        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        self._build_ui()

    # --- public API ---

    @property
    def duration(self) -> float:
        return self._duration_ms / 1000.0

    @property
    def current_time(self) -> float:
        return self._player.position() / 1000.0

    def load_video(self, path: str | Path):
        self.stop()
        resolved = str(Path(path).resolve())
        # One-shot FPS read from source file
        cap = cv2.VideoCapture(resolved)
        self._fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.release()
        self._player.setSource(QUrl.fromLocalFile(resolved))

    def set_marks(self, timestamps: list[float]):
        self._slider.set_marks(timestamps, self.duration)

    def seek_to(self, seconds: float):
        self._seek(int(seconds * 1000))

    def toggle_play(self):
        if self._on_transport:
            self._on_transport("toggle_play")
            return
        if self._want_play:
            self.pause()
        else:
            self.play()

    def play(self):
        self._want_play = True
        self._btn_play.setText("Pause")
        self._player.play()

    def pause(self):
        self._want_play = False
        self._btn_play.setText("Play")
        self._player.pause()

    def set_muted(self, muted: bool):
        if muted:
            self._saved_volume = self._audio_output.volume()
            self._audio_output.setVolume(0.0)
        else:
            self._audio_output.setVolume(getattr(self, "_saved_volume", 1.0))

    def stop(self):
        self._want_play = False
        self._btn_play.setText("Play")
        self._player.stop()

    def set_transport_callback(self, cb: callable | None):
        """Set callback(action, *args) that intercepts transport actions."""
        self._on_transport = cb

    def set_external_control(self, enabled: bool):
        """When True, slider and time label are not auto-updated from video position."""
        self._external_control = enabled

    def set_slider_range_ms(self, duration_ms: int):
        """Override slider range (e.g. for preview mode audio duration)."""
        self._slider.setRange(0, duration_ms)

    def set_slider_position_ms(self, position_ms: int):
        """Set slider position externally."""
        if not self._seeking:
            self._slider.setValue(position_ms)

    def update_time_label_external(self, current_s: float, total_s: float):
        """Update time label from external source."""
        self._time_label.setText(f"{self._fmt(current_s)} / {self._fmt(total_s)}")

    def restore_slider_range(self):
        """Restore slider range to the loaded video duration."""
        self._slider.setRange(0, self._duration_ms)
        self._slider.setValue(self._player.position())
        self._update_time_label()

    # --- UI construction ---

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Video display — takes all available space
        self._display = QVideoWidget()
        self._display.setMinimumSize(320, 180)
        self._display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._display.setStyleSheet("background-color: #111; border-radius: 4px;")
        self._player.setVideoOutput(self._display)
        layout.addWidget(self._display, stretch=1)

        # Slider (operates in milliseconds)
        self._slider = ClickSlider(Qt.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.setMinimumHeight(28)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        layout.addWidget(self._slider)

        # Controls row
        controls = QHBoxLayout()
        controls.setSpacing(6)

        btn_style = "min-width: 44px; min-height: 32px; font-size: 16px;"
        play_style = "min-width: 80px; min-height: 32px; font-size: 14px; font-weight: bold;"

        self._btn_start = QPushButton("\u23EE")   # ⏮
        self._btn_start.setStyleSheet(btn_style)
        self._btn_start.setToolTip("Go to start")
        self._btn_start.clicked.connect(self._go_start)

        self._btn_jump_back = QPushButton("\u25C1\u25C1")  # ◁◁
        self._btn_jump_back.setStyleSheet(btn_style)
        self._btn_jump_back.setToolTip("Jump back 5 s")
        self._btn_jump_back.setAutoRepeat(True)
        self._btn_jump_back.setAutoRepeatDelay(400)
        self._btn_jump_back.setAutoRepeatInterval(200)
        self._btn_jump_back.clicked.connect(self._jump_back)

        self._btn_prev = QPushButton("\u25C1")    # ◁
        self._btn_prev.setStyleSheet(btn_style)
        self._btn_prev.setToolTip("Step back 1 frame")
        self._btn_prev.setAutoRepeat(True)
        self._btn_prev.setAutoRepeatDelay(400)
        self._btn_prev.setAutoRepeatInterval(80)
        self._btn_prev.clicked.connect(self._step_back)

        self._btn_play = QPushButton("Play")
        self._btn_play.setStyleSheet(play_style)
        self._btn_play.clicked.connect(self.toggle_play)

        self._btn_next = QPushButton("\u25B7")    # ▷
        self._btn_next.setStyleSheet(btn_style)
        self._btn_next.setToolTip("Step forward 1 frame")
        self._btn_next.setAutoRepeat(True)
        self._btn_next.setAutoRepeatDelay(400)
        self._btn_next.setAutoRepeatInterval(80)
        self._btn_next.clicked.connect(self._step_forward)

        self._btn_jump_fwd = QPushButton("\u25B7\u25B7")  # ▷▷
        self._btn_jump_fwd.setStyleSheet(btn_style)
        self._btn_jump_fwd.setToolTip("Jump forward 5 s")
        self._btn_jump_fwd.setAutoRepeat(True)
        self._btn_jump_fwd.setAutoRepeatDelay(400)
        self._btn_jump_fwd.setAutoRepeatInterval(200)
        self._btn_jump_fwd.clicked.connect(self._jump_forward)

        self._btn_end = QPushButton("\u23ED")     # ⏭
        self._btn_end.setStyleSheet(btn_style)
        self._btn_end.setToolTip("Go to end")
        self._btn_end.clicked.connect(self._go_end)

        self._time_label = QLabel("00:00.00 / 00:00.00")
        self._time_label.setStyleSheet("font-size: 14px; font-family: monospace; min-width: 170px;")

        controls.addStretch()
        controls.addWidget(self._btn_start)
        controls.addWidget(self._btn_jump_back)
        controls.addWidget(self._btn_prev)
        controls.addWidget(self._btn_play)
        controls.addWidget(self._btn_next)
        controls.addWidget(self._btn_jump_fwd)
        controls.addWidget(self._btn_end)
        controls.addStretch()
        controls.addWidget(self._time_label)

        layout.addLayout(controls)

    # --- QMediaPlayer signal handlers ---

    def _on_duration_changed(self, duration_ms: int):
        self._duration_ms = duration_ms
        self._slider.setRange(0, duration_ms)
        self._slider.setValue(0)
        self._update_time_label()

    def _on_position_changed(self, position_ms: int):
        if not self._external_control:
            if not self._seeking:
                self._slider.setValue(position_ms)
            self._update_time_label()
        self.position_changed.emit(position_ms / 1000.0)

    def _on_state_changed(self, state):
        # Only update UI from actual user-driven state changes.
        # Ignore transient states caused by setPosition() seeks.
        pass

    def _on_media_status(self, status):
        # Show first frame once media is loaded
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._player.pause()

    def _on_error(self, error, error_string):
        print(f"VideoPlayer error: {error_string}")

    # --- seeking ---

    def _seek(self, position_ms: int):
        """Seek to *position_ms* and resume playback if the user intended it."""
        self._player.setPosition(position_ms)
        if self._want_play:
            self._player.play()

    def _user_seek(self, position_ms: int):
        """Seek triggered by user interaction — emits user_seeked."""
        self._seek(position_ms)
        self.user_seeked.emit()

    def _on_slider_pressed(self):
        self._seeking = True

    def _on_slider_released(self):
        if self._on_transport:
            self._on_transport("seek", self._slider.value())
            self._seeking = False
            return
        self._user_seek(self._slider.value())
        self._seeking = False

    def _on_slider_moved(self, value: int):
        if self._on_transport:
            self._on_transport("slider_moved", value)
            return
        self._player.setPosition(value)

    # --- transport buttons ---

    def _go_start(self):
        if self._on_transport:
            self._on_transport("go_start")
            return
        self._user_seek(0)

    def _go_end(self):
        if self._on_transport:
            self._on_transport("go_end")
            return
        self._user_seek(max(0, self._duration_ms - 100))

    def _jump_forward(self):
        if self._on_transport:
            self._on_transport("jump_forward")
            return
        self._user_seek(min(self._player.position() + 5000, self._duration_ms))

    def _jump_back(self):
        if self._on_transport:
            self._on_transport("jump_back")
            return
        self._user_seek(max(self._player.position() - 5000, 0))

    def _step_forward(self):
        if self._on_transport:
            self._on_transport("step_forward")
            return
        frame_ms = int(1000.0 / self._fps)
        self._user_seek(min(self._player.position() + frame_ms, self._duration_ms))

    def _step_back(self):
        if self._on_transport:
            self._on_transport("step_back")
            return
        frame_ms = int(1000.0 / self._fps)
        self._user_seek(max(self._player.position() - frame_ms, 0))

    # --- helpers ---

    def _update_time_label(self):
        self._time_label.setText(
            f"{self._fmt(self.current_time)} / {self._fmt(self.duration)}"
        )

    @staticmethod
    def _fmt(seconds: float) -> str:
        m, s = divmod(seconds, 60)
        return f"{int(m):02d}:{s:05.2f}"

    def wheelEvent(self, event):
        delta = event.angleDelta().y()  # typically ±120 per notch
        step_ms = int(delta / 120 * 1000)  # 1 s per notch
        if self._on_transport:
            self._on_transport("wheel", step_ms)
            event.accept()
            return
        new_pos = max(0, min(self._player.position() + step_ms, self._duration_ms))
        self._user_seek(new_pos)
        event.accept()

    def closeEvent(self, event):
        self._player.stop()
        super().closeEvent(event)
