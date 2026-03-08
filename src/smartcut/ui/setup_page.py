from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from smartcut.ui.video_player import VideoPlayer

_VIDEO_FILTER = "Video Files (*.mp4 *.avi *.mkv *.mov *.webm);;All Files (*)"
_AUDIO_FILTER = "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a);;All Files (*)"


class SetupPage(QWidget):
    """Page 1: File selection, video preview, marks, and analysis settings.

    Layout prioritises video preview — settings and marks are in a compact
    tabbed panel at the bottom.
    """

    analyze_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._marks: list[float] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(6)

        # --- Compact file selection (single horizontal row per file) ---
        file_row = QHBoxLayout()
        file_row.setSpacing(6)

        file_row.addWidget(QLabel("Video:"))
        self._video_path = QLineEdit()
        self._video_path.setPlaceholderText("Select source video...")
        self._video_path.setReadOnly(True)
        file_row.addWidget(self._video_path, stretch=1)
        btn_video = QPushButton("Browse")
        btn_video.clicked.connect(self._browse_video)
        file_row.addWidget(btn_video)

        file_row.addWidget(QLabel("  Audio:"))
        self._audio_path = QLineEdit()
        self._audio_path.setPlaceholderText("Select audio track...")
        self._audio_path.setReadOnly(True)
        file_row.addWidget(self._audio_path, stretch=1)
        btn_audio = QPushButton("Browse")
        btn_audio.clicked.connect(self._browse_audio)
        file_row.addWidget(btn_audio)

        root.addLayout(file_row)

        # --- Video player (dominant area) ---
        self._player = VideoPlayer()
        root.addWidget(self._player, stretch=10)

        # --- Bottom tabbed panel: Marks | Settings ---
        tabs = QTabWidget()
        tabs.setMaximumHeight(180)

        # Marks tab
        marks_tab = QWidget()
        marks_layout = QVBoxLayout(marks_tab)
        marks_layout.setContentsMargins(6, 6, 6, 6)

        marks_btns = QHBoxLayout()
        btn_add_mark = QPushButton("+ Add Mark at Current Position")
        btn_add_mark.clicked.connect(self._add_mark)
        btn_clear_marks = QPushButton("Clear All")
        btn_clear_marks.clicked.connect(self._clear_marks)
        marks_btns.addWidget(btn_add_mark)
        marks_btns.addWidget(btn_clear_marks)
        marks_btns.addStretch()
        marks_layout.addLayout(marks_btns)

        self._marks_list = QListWidget()
        marks_layout.addWidget(self._marks_list)
        tabs.addTab(marks_tab, "Marks")

        # Settings tab — compact 2-column form
        settings_tab = QWidget()
        settings_outer = QHBoxLayout(settings_tab)
        settings_outer.setContentsMargins(6, 6, 6, 6)

        col1 = QFormLayout()
        col1.setSpacing(6)
        self._analysis_fps = QDoubleSpinBox()
        self._analysis_fps.setRange(0.5, 30.0)
        self._analysis_fps.setValue(3.0)
        self._analysis_fps.setSingleStep(0.5)
        col1.addRow("Analysis FPS:", self._analysis_fps)

        self._segment_hop = QDoubleSpinBox()
        self._segment_hop.setRange(0.1, 5.0)
        self._segment_hop.setValue(0.5)
        self._segment_hop.setSingleStep(0.1)
        col1.addRow("Segment Hop (s):", self._segment_hop)

        self._min_segment = QDoubleSpinBox()
        self._min_segment.setRange(0.5, 30.0)
        self._min_segment.setValue(1.0)
        self._min_segment.setSingleStep(0.5)
        col1.addRow("Min Segment (s):", self._min_segment)

        settings_outer.addLayout(col1)

        col2 = QFormLayout()
        col2.setSpacing(6)
        self._max_segment = QDoubleSpinBox()
        self._max_segment.setRange(1.0, 60.0)
        self._max_segment.setValue(8.0)
        self._max_segment.setSingleStep(1.0)
        col2.addRow("Max Segment (s):", self._max_segment)

        self._gpu_check = QCheckBox("Enabled")
        self._gpu_check.setChecked(True)
        col2.addRow("GPU:", self._gpu_check)

        self._gpu_batch = QSpinBox()
        self._gpu_batch.setRange(8, 512)
        self._gpu_batch.setValue(64)
        self._gpu_batch.setSingleStep(16)
        col2.addRow("GPU Batch:", self._gpu_batch)

        settings_outer.addLayout(col2)
        settings_outer.addStretch()

        tabs.addTab(settings_tab, "Settings")
        root.addWidget(tabs)

        # --- Analyze button ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_analyze = QPushButton("Analyze")
        self._btn_analyze.setProperty("primary", True)
        self._btn_analyze.clicked.connect(self._on_analyze)
        btn_row.addWidget(self._btn_analyze)
        btn_row.addStretch()
        root.addLayout(btn_row)

    # --- File browsing ---

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", _VIDEO_FILTER)
        if path:
            self._video_path.setText(path)
            self._player.load_video(path)

    def _browse_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Audio", "", _AUDIO_FILTER)
        if path:
            self._audio_path.setText(path)

    # --- Marks ---

    def _add_mark(self):
        t = self._player.current_time
        # avoid duplicate (within 0.01s)
        if any(abs(t - m) < 0.01 for m in self._marks):
            return
        self._marks.append(t)
        self._marks.sort()
        self._refresh_marks_ui()

    def _clear_marks(self):
        self._marks.clear()
        self._refresh_marks_ui()

    def _refresh_marks_ui(self):
        self._marks_list.clear()
        for t in self._marks:
            m, s = divmod(t, 60)
            self._marks_list.addItem(QListWidgetItem(f"{int(m):02d}:{s:05.2f}"))
        self._player.set_marks(self._marks)

    # --- Analyze ---

    def _on_analyze(self):
        video = self._video_path.text().strip()
        audio = self._audio_path.text().strip()
        if not video or not audio:
            return

        self._btn_analyze.setEnabled(False)
        self._btn_analyze.setText("Analyzing...")
        self.analyze_requested.emit({
            "video_path": Path(video),
            "audio_path": Path(audio),
            "analysis_fps": self._analysis_fps.value(),
            "segment_hop": self._segment_hop.value(),
            "min_segment_duration": self._min_segment.value(),
            "max_segment_duration": self._max_segment.value(),
            "use_gpu": self._gpu_check.isChecked(),
            "gpu_batch_size": self._gpu_batch.value(),
            "include_timestamps": list(self._marks),
        })

    def set_analyze_enabled(self, enabled: bool):
        self._btn_analyze.setEnabled(enabled)
        self._btn_analyze.setText("Analyze" if enabled else "Analyzing...")

    @property
    def video_path(self) -> str:
        return self._video_path.text().strip()

    @property
    def video_duration(self) -> float:
        return self._player.duration
