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
        painter = QPainter(self)
        pen = QPen(QColor("#ff5252"), 2)
        painter.setPen(pen)
        for norm in self._marks:
            x = int(norm * self.width())
            painter.drawLine(x, 0, x, self.height())
        painter.end()


class VideoPlayer(QWidget):
    """QMediaPlayer-based video player with audio support."""

    position_changed = Signal(float)  # current time in seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)

        self._duration_ms = 0
        self._fps = 30.0  # overwritten with real source FPS in load_video()
        self._playing = False
        self._seeking = False

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

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self):
        self._player.play()

    def pause(self):
        self._player.pause()

    def stop(self):
        self._player.stop()

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

        self._btn_prev = QPushButton("\u23EA")    # ⏪
        self._btn_prev.setStyleSheet(btn_style)
        self._btn_prev.setToolTip("Step back 1 frame")
        self._btn_prev.clicked.connect(self._step_back)

        self._btn_play = QPushButton("Play")
        self._btn_play.setStyleSheet(play_style)
        self._btn_play.clicked.connect(self.toggle_play)

        self._btn_next = QPushButton("\u23E9")    # ⏩
        self._btn_next.setStyleSheet(btn_style)
        self._btn_next.setToolTip("Step forward 1 frame")
        self._btn_next.clicked.connect(self._step_forward)

        self._btn_end = QPushButton("\u23ED")     # ⏭
        self._btn_end.setStyleSheet(btn_style)
        self._btn_end.setToolTip("Go to end")
        self._btn_end.clicked.connect(self._go_end)

        self._time_label = QLabel("00:00.00 / 00:00.00")
        self._time_label.setStyleSheet("font-size: 14px; font-family: monospace; min-width: 170px;")

        controls.addWidget(self._btn_start)
        controls.addWidget(self._btn_prev)
        controls.addWidget(self._btn_play)
        controls.addWidget(self._btn_next)
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
        if not self._seeking:
            self._slider.setValue(position_ms)
        self._update_time_label()
        self.position_changed.emit(position_ms / 1000.0)

    def _on_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._playing = True
            self._btn_play.setText("Pause")
        else:
            self._playing = False
            self._btn_play.setText("Play")

    def _on_media_status(self, status):
        # Show first frame once media is loaded
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._player.pause()

    def _on_error(self, error, error_string):
        print(f"VideoPlayer error: {error_string}")

    # --- seeking ---

    def _on_slider_pressed(self):
        self._seeking = True

    def _on_slider_released(self):
        self._player.setPosition(self._slider.value())
        self._seeking = False

    def _on_slider_moved(self, value: int):
        self._player.setPosition(value)

    # --- transport buttons ---

    def _go_start(self):
        self.pause()
        self._player.setPosition(0)

    def _go_end(self):
        self.pause()
        self._player.setPosition(max(0, self._duration_ms - 100))

    def _step_forward(self):
        if self._playing:
            self.pause()
        frame_ms = int(1000.0 / self._fps)
        new_pos = min(self._player.position() + frame_ms, self._duration_ms)
        self._player.setPosition(new_pos)

    def _step_back(self):
        if self._playing:
            self.pause()
        frame_ms = int(1000.0 / self._fps)
        new_pos = max(self._player.position() - frame_ms, 0)
        self._player.setPosition(new_pos)

    # --- helpers ---

    def _update_time_label(self):
        self._time_label.setText(
            f"{self._fmt(self.current_time)} / {self._fmt(self.duration)}"
        )

    @staticmethod
    def _fmt(seconds: float) -> str:
        m, s = divmod(seconds, 60)
        return f"{int(m):02d}:{s:05.2f}"

    def closeEvent(self, event):
        self._player.stop()
        super().closeEvent(event)
