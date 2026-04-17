from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from trailvideocut.ui.exclusions_tab import ExclusionsTab
from trailvideocut.ui.video_player import VideoPlayer
from trailvideocut.video.exclusions import (
    ExclusionRange,
    load_exclusions,
    save_exclusions,
)
from trailvideocut.video.marks import load_marks, save_marks

_VIDEO_FILTER = "Video Files (*.mp4 *.avi *.mkv *.mov *.webm);;All Files (*)"
_AUDIO_FILTER = "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a);;All Files (*)"


class SetupPage(QWidget):
    """Page 1: File selection, video preview, marks, and analysis settings.

    Layout prioritises video preview — settings and marks are in a compact
    tabbed panel at the bottom.
    """

    analyze_requested = Signal(dict)
    go_to_review_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._marks: list[float] = []
        self._selected_mark_index: int = -1
        self._excluded_ranges: list[tuple[float, float]] = []
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
        self._btn_remove_mark = QPushButton("\u2715 Remove")
        self._btn_remove_mark.setEnabled(False)
        self._btn_remove_mark.clicked.connect(self._remove_mark)
        btn_clear_marks = QPushButton("Clear All")
        btn_clear_marks.clicked.connect(self._clear_marks)
        marks_btns.addWidget(btn_add_mark)
        marks_btns.addWidget(self._btn_remove_mark)
        marks_btns.addWidget(btn_clear_marks)
        marks_btns.addStretch()
        marks_layout.addLayout(marks_btns)

        # Horizontal scrollable chip area
        self._marks_scroll = QScrollArea()
        self._marks_scroll.setWidgetResizable(True)
        self._marks_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._marks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._marks_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._marks_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._marks_container = QWidget()
        self._marks_chip_layout = QHBoxLayout(self._marks_container)
        self._marks_chip_layout.setContentsMargins(0, 0, 0, 0)
        self._marks_chip_layout.setSpacing(6)
        self._marks_chip_layout.addStretch()
        self._marks_scroll.setWidget(self._marks_container)
        marks_layout.addWidget(self._marks_scroll)
        tabs.addTab(marks_tab, "Marks")

        # Excluded tab — skip time ranges during clip selection
        self._exclusions_tab = ExclusionsTab()
        self._exclusions_tab.ranges_changed.connect(self._on_exclusions_changed)
        tabs.addTab(self._exclusions_tab, "Excluded")

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
        self._analysis_fps.setToolTip("Frames per second sampled during analysis. Higher = more accurate but slower.")
        col1.addRow("Analysis FPS:", self._analysis_fps)

        self._segment_hop = QDoubleSpinBox()
        self._segment_hop.setRange(0.1, 5.0)
        self._segment_hop.setValue(0.5)
        self._segment_hop.setSingleStep(0.1)
        self._segment_hop.setToolTip("Step size in seconds for the sliding analysis window. Smaller = finer detection but slower.")
        col1.addRow("Segment Hop (s):", self._segment_hop)

        self._min_segment = QDoubleSpinBox()
        self._min_segment.setRange(0.5, 30.0)
        self._min_segment.setValue(1.5)
        self._min_segment.setSingleStep(0.5)
        self._min_segment.setToolTip("Minimum clip duration in seconds. Clips shorter than this are discarded.")
        col1.addRow("Min Segment (s):", self._min_segment)

        settings_outer.addLayout(col1)

        col2 = QFormLayout()
        col2.setSpacing(6)
        self._max_segment = QDoubleSpinBox()
        self._max_segment.setRange(1.0, 60.0)
        self._max_segment.setValue(8.0)
        self._max_segment.setSingleStep(1.0)
        self._max_segment.setToolTip("Maximum clip duration in seconds. Longer segments are split.")
        col2.addRow("Max Segment (s):", self._max_segment)

        self._gpu_check = QCheckBox("Enabled")
        self._gpu_check.setChecked(True)
        self._gpu_check.setToolTip("Use GPU acceleration for video analysis (requires NVIDIA GPU).")
        col2.addRow("GPU:", self._gpu_check)

        self._gpu_batch = QSpinBox()
        self._gpu_batch.setRange(8, 512)
        self._gpu_batch.setValue(64)
        self._gpu_batch.setSingleStep(16)
        self._gpu_batch.setToolTip("Frames processed simultaneously on GPU. Higher = faster but uses more VRAM.")
        col2.addRow("GPU Batch:", self._gpu_batch)

        settings_outer.addLayout(col2)
        settings_outer.addStretch()

        tabs.addTab(settings_tab, "Settings")

        # Progress bar (hidden by default)
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumHeight(16)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.hide()
        root.addWidget(self._progress_bar)

        # Tabs + Analyze button side by side
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addWidget(tabs, stretch=1)

        right_btns = QVBoxLayout()
        self._btn_go_review = QPushButton("Go to Review >>")
        self._btn_go_review.setProperty("primary", True)
        self._btn_go_review.clicked.connect(self.go_to_review_requested.emit)
        self._btn_go_review.hide()
        self._btn_analyze = QPushButton("Analyze")
        self._btn_analyze.setProperty("primary", True)
        self._btn_analyze.setEnabled(False)
        self._btn_analyze.clicked.connect(self._on_analyze)
        right_btns.addWidget(self._btn_go_review)
        right_btns.addWidget(self._btn_analyze)
        bottom_row.addLayout(right_btns)

        root.addLayout(bottom_row)

        # Enable Analyze only when both paths are set
        self._video_path.textChanged.connect(self._update_analyze_enabled)
        self._audio_path.textChanged.connect(self._update_analyze_enabled)

        # Keyboard shortcuts
        ctx = Qt.WidgetWithChildrenShortcut
        QShortcut(Qt.Key_Space, self, self._player.toggle_play, context=ctx)
        sc_left = QShortcut(Qt.Key_Left, self, self._on_step_back_pressed, context=ctx)
        sc_left.setAutoRepeat(False)
        sc_right = QShortcut(Qt.Key_Right, self, self._on_step_forward_pressed, context=ctx)
        sc_right.setAutoRepeat(False)
        QShortcut(Qt.Key_Up, self, self._player._jump_forward, context=ctx)
        QShortcut(Qt.Key_Down, self, self._player._jump_back, context=ctx)
        QShortcut(Qt.Key_Home, self, self._player._go_start, context=ctx)
        QShortcut(Qt.Key_End, self, self._player._go_end, context=ctx)
        QShortcut(Qt.Key_A, self, self._add_mark, context=ctx)
        QShortcut(Qt.Key_D, self, self._remove_mark, context=ctx)
        QShortcut(Qt.Key_I, self, self._exclusions_tab.capture_start, context=ctx)
        QShortcut(Qt.Key_O, self, self._exclusions_tab.capture_end, context=ctx)
        QShortcut(Qt.Key_Escape, self, self._exclusions_tab.cancel_pending, context=ctx)

        # Keep the Excluded tab in sync with the video player's current time
        self._player.position_changed.connect(self._exclusions_tab.set_player_position)

    # --- Key-hold stepping ---

    def _on_step_forward_pressed(self):
        self._player._step_forward()
        self._player.start_step_hold(+1)

    def _on_step_back_pressed(self):
        self._player._step_back()
        self._player.start_step_hold(-1)

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat() and event.key() in (Qt.Key_Left, Qt.Key_Right):
            self._player.stop_step_hold()
        super().keyReleaseEvent(event)

    # --- File browsing ---

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", _VIDEO_FILTER)
        if path:
            self._video_path.setText(path)
            self._player.load_video(path)
            self._auto_load_exclusions(Path(path))
            self._auto_load_marks(Path(path))

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
        self._persist_marks()

    def _clear_marks(self):
        self._marks.clear()
        self._selected_mark_index = -1
        self._btn_remove_mark.setEnabled(False)
        self._refresh_marks_ui()
        self._persist_marks()

    def _remove_mark(self):
        # Prefer the chip-selected mark; otherwise fall back to the mark
        # nearest the current player position so `D` mirrors `A` without
        # requiring the user to click a chip first.
        index = self._selected_mark_index
        if not (0 <= index < len(self._marks)):
            if not self._marks:
                return
            t = self._player.current_time
            index = min(range(len(self._marks)), key=lambda i: abs(self._marks[i] - t))
        del self._marks[index]
        self._selected_mark_index = -1
        self._btn_remove_mark.setEnabled(False)
        self._refresh_marks_ui()
        self._persist_marks()

    def _persist_marks(self):
        video_text = self._video_path.text().strip()
        if not video_text:
            return
        save_marks(Path(video_text), list(self._marks))

    def _auto_load_marks(self, video_path: Path):
        self._marks = load_marks(video_path)
        self._selected_mark_index = -1
        self._btn_remove_mark.setEnabled(False)
        self._refresh_marks_ui()

    def _select_mark(self, index: int):
        if self._selected_mark_index == index:
            self._selected_mark_index = -1
            self._btn_remove_mark.setEnabled(False)
        else:
            self._selected_mark_index = index
            self._btn_remove_mark.setEnabled(True)
            self._player.seek_to(self._marks[index])
        self._refresh_marks_ui()

    def _refresh_marks_ui(self):
        # Clear existing chips
        while self._marks_chip_layout.count():
            item = self._marks_chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        chip_style = (
            "QPushButton { border-radius: 12px; padding: 4px 10px;"
            " font-family: monospace; font-size: 13px;"
            " background: #3a3a3a; color: #e0e0e0; border: 1px solid #555; }"
            " QPushButton:hover { background: #4a4a4a; }"
        )
        selected_style = (
            "QPushButton { border-radius: 12px; padding: 4px 10px;"
            " font-family: monospace; font-size: 13px;"
            " background: #2196F3; color: #fff; border: 1px solid #2196F3; }"
        )

        for i, t in enumerate(self._marks):
            m, s = divmod(t, 60)
            chip = QPushButton(f"{int(m):02d}:{s:05.2f}")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(selected_style if i == self._selected_mark_index else chip_style)
            chip.clicked.connect(lambda checked, idx=i: self._select_mark(idx))
            self._marks_chip_layout.addWidget(chip)

        self._marks_chip_layout.addStretch()
        self._player.set_marks(self._marks)

    # --- Exclusions ---

    def _on_exclusions_changed(self, ranges: list[tuple[float, float]]):
        self._excluded_ranges = list(ranges)
        video_text = self._video_path.text().strip()
        if video_text:
            exclusion_objs = [ExclusionRange(s, e) for s, e in ranges]
            save_exclusions(Path(video_text), exclusion_objs)
        # Scrubber overlay: let the video player draw the shaded spans.
        if hasattr(self._player, "set_excluded_ranges"):
            self._player.set_excluded_ranges(list(ranges))

    def _auto_load_exclusions(self, video_path: Path):
        loaded = load_exclusions(video_path)
        ranges = [(r.start, r.end) for r in loaded]
        self._excluded_ranges = ranges
        self._exclusions_tab.set_ranges(ranges)
        if hasattr(self._player, "set_excluded_ranges"):
            self._player.set_excluded_ranges(list(ranges))

    # --- Analyze ---

    def _on_analyze(self):
        video = self._video_path.text().strip()
        audio = self._audio_path.text().strip()
        if not video or not audio:
            return

        self._btn_analyze.setEnabled(False)
        self._btn_analyze.setText("Analyzing...")
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._progress_bar.show()
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
            "excluded_ranges": list(self._excluded_ranges),
        })

    def _update_analyze_enabled(self):
        has_both = bool(self._video_path.text().strip()) and bool(self._audio_path.text().strip())
        self._btn_analyze.setEnabled(has_both)

    def set_progress(self, current: int, total: int):
        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
        self._progress_bar.show()

    def set_progress_status(self, message: str):
        self._progress_bar.setFormat(f"{message}  %p%")
        self._progress_bar.setRange(0, 0)  # indeterminate until progress arrives
        self._progress_bar.show()

    def reset_progress(self):
        self._progress_bar.hide()
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p%")

    def set_analyze_enabled(self, enabled: bool):
        if enabled:
            label = "Reanalyze" if self._btn_go_review.isVisible() else "Analyze"
            self._btn_analyze.setText(label)
            self._update_analyze_enabled()
            self.reset_progress()
        else:
            self._btn_analyze.setEnabled(False)
            self._btn_analyze.setText("Analyzing...")

    def show_go_to_review(self, visible: bool):
        self._btn_go_review.setVisible(visible)
        self._btn_analyze.setText("Reanalyze" if visible else "Analyze")

    @property
    def video_path(self) -> str:
        return self._video_path.text().strip()

    @property
    def video_duration(self) -> float:
        return self._player.duration
