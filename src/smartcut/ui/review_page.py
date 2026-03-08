from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from smartcut.audio.models import AudioAnalysis, MusicSection
from smartcut.editor.models import CutPlan, EditDecision
from smartcut.ui.timeline import TimelineWidget
from smartcut.ui.video_player import VideoPlayer


class ReviewPage(QWidget):
    """Page 2: Timeline review, clip editing, and render settings."""

    back_requested = Signal()
    export_requested = Signal(dict)  # render settings

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio: AudioAnalysis | None = None
        self._sections: list[MusicSection] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # --- Top navigation ---
        nav = QHBoxLayout()
        btn_back = QPushButton("<< Back to Setup")
        btn_back.clicked.connect(self.back_requested.emit)
        self._btn_export = QPushButton("Export >>")
        self._btn_export.setProperty("primary", True)
        self._btn_export.clicked.connect(self._on_export)
        nav.addWidget(btn_back)
        nav.addStretch()
        nav.addWidget(self._btn_export)
        root.addLayout(nav)

        # --- Summary ---
        self._summary = QLabel()
        self._summary.setProperty("name", "heading")
        self._summary.setStyleSheet("font-size: 13px; color: #ccc; padding: 4px;")
        root.addWidget(self._summary)

        # --- Timeline ---
        timeline_group = QGroupBox("Source Video Timeline")
        timeline_layout = QVBoxLayout(timeline_group)
        self._timeline = TimelineWidget()
        self._timeline.clip_selected.connect(self._on_clip_selected)
        self._timeline.clip_moved.connect(self._on_clip_moved)
        timeline_layout.addWidget(self._timeline)
        root.addWidget(timeline_group)

        # --- Main content: video player on top, clip info + settings on bottom ---
        main_splitter = QSplitter(Qt.Vertical)

        # Video player
        self._player = VideoPlayer()
        main_splitter.addWidget(self._player)

        # Bottom horizontal splitter: clip details + render settings
        bottom_splitter = QSplitter(Qt.Horizontal)

        # Clip details with prev/next navigation
        clip_group = QGroupBox("Selected Clip")
        clip_layout = QVBoxLayout(clip_group)
        self._clip_info = QLabel("No clip selected")
        self._clip_info.setWordWrap(True)
        self._clip_info.setStyleSheet("font-family: monospace; font-size: 12px;")
        clip_layout.addWidget(self._clip_info)

        clip_nav = QHBoxLayout()
        self._btn_prev_clip = QPushButton("<< Prev Clip")
        self._btn_prev_clip.clicked.connect(self._prev_clip)
        self._btn_next_clip = QPushButton("Next Clip >>")
        self._btn_next_clip.clicked.connect(self._next_clip)
        clip_nav.addWidget(self._btn_prev_clip)
        clip_nav.addWidget(self._btn_next_clip)
        clip_layout.addLayout(clip_nav)

        clip_layout.addStretch()
        bottom_splitter.addWidget(clip_group)

        # Render settings
        render_group = QGroupBox("Render Settings")
        render_layout = QFormLayout(render_group)

        self._transition = QComboBox()
        self._transition.addItems(["crossfade", "hard_cut"])
        render_layout.addRow("Transition:", self._transition)

        self._crossfade_dur = QDoubleSpinBox()
        self._crossfade_dur.setRange(0.0, 2.0)
        self._crossfade_dur.setValue(0.2)
        self._crossfade_dur.setSingleStep(0.05)
        render_layout.addRow("Crossfade (s):", self._crossfade_dur)

        self._preset = QComboBox()
        self._preset.addItems(["ultrafast", "superfast", "veryfast", "faster",
                               "fast", "medium", "slow", "slower", "veryslow"])
        self._preset.setCurrentText("veryslow")
        render_layout.addRow("Preset:", self._preset)

        self._output_fps = QDoubleSpinBox()
        self._output_fps.setRange(0, 120.0)
        self._output_fps.setValue(0)
        self._output_fps.setSingleStep(1.0)
        self._output_fps.setSpecialValueText("auto (source)")
        render_layout.addRow("FPS:", self._output_fps)

        self._threads = QSpinBox()
        self._threads.setRange(0, 64)
        self._threads.setValue(0)
        self._threads.setSpecialValueText("auto")
        render_layout.addRow("Threads:", self._threads)

        bottom_splitter.addWidget(render_group)
        bottom_splitter.setSizes([350, 250])

        main_splitter.addWidget(bottom_splitter)
        main_splitter.setSizes([400, 200])

        root.addWidget(main_splitter, stretch=1)

        # Keyboard shortcuts (same as setup page)
        ctx = Qt.WidgetWithChildrenShortcut
        QShortcut(Qt.Key_Space, self, self._player.toggle_play, context=ctx)
        QShortcut(Qt.Key_Left, self, self._player._step_back, context=ctx)
        QShortcut(Qt.Key_Right, self, self._player._step_forward, context=ctx)
        QShortcut(Qt.Key_Up, self, self._player._jump_forward, context=ctx)
        QShortcut(Qt.Key_Down, self, self._player._jump_back, context=ctx)
        QShortcut(Qt.Key_Home, self, self._player._go_start, context=ctx)
        QShortcut(Qt.Key_End, self, self._player._go_end, context=ctx)

    def set_data(
        self,
        audio: AudioAnalysis,
        cut_plan: CutPlan,
        video_duration: float,
        video_path: str = "",
        marks: list[float] | None = None,
    ):
        self._audio = audio
        self._sections = audio.sections

        # Summary
        self._summary.setText(
            f"Tempo: {audio.tempo:.0f} BPM  |  "
            f"Beats: {len(audio.beats)}  |  "
            f"Clips: {len(cut_plan.decisions)}  |  "
            f"CV: {cut_plan.score_cv:.3f}  |  "
            f"Duration: {audio.duration:.1f}s"
        )

        # Timeline
        self._timeline.set_data(cut_plan.decisions, video_duration)

        # Marks on timeline and player
        if marks:
            self._timeline.set_marks(marks)
            self._player.set_marks(marks)

        # Load video and connect playback cursor
        if video_path:
            self._player.load_video(video_path)
        self._player.position_changed.connect(self._timeline.set_cursor_position)

        # Clip info
        self._clip_info.setText("Click a clip on the timeline to see details")

    def _on_clip_selected(self, index: int):
        if index < 0 or index >= len(self._timeline.clips):
            self._clip_info.setText("No clip selected")
            return

        clip = self._timeline.clips[index]
        duration = clip.source_end - clip.source_start
        target_dur = clip.target_end - clip.target_start

        # Seek video to clip start
        self._player.seek_to(clip.source_start)

        # Find section
        section_label = "unknown"
        section_energy = 0.0
        mid = (clip.source_start + clip.source_end) / 2
        for sec in self._sections:
            if sec.start_time <= mid < sec.end_time:
                section_label = sec.label
                section_energy = sec.energy
                break

        self._clip_info.setText(
            f"Clip {index + 1} of {len(self._timeline.clips)}\n\n"
            f"Source:   {clip.source_start:.2f}s - {clip.source_end:.2f}s\n"
            f"Duration: {duration:.2f}s\n"
            f"Target:   {clip.target_start:.2f}s - {clip.target_end:.2f}s\n"
            f"Target dur: {target_dur:.2f}s\n"
            f"Score:    {clip.interest_score:.3f}\n\n"
            f"Section:  {section_label} (energy: {section_energy:.2f})"
        )

    def _on_clip_moved(self, index: int, new_start: float, new_end: float):
        """Called after a clip is dragged to a new source position."""
        self._on_clip_selected(index)

    def _on_export(self):
        settings = {
            "transition_style": self._transition.currentText(),
            "crossfade_duration": self._crossfade_dur.value(),
            "output_preset": self._preset.currentText(),
            "output_fps": self._output_fps.value(),
            "output_threads": self._threads.value(),
        }
        self.export_requested.emit(settings)

    def _prev_clip(self):
        clips = self._timeline.clips
        if not clips:
            return
        current = self._timeline.selected_index
        new_index = max(0, current - 1) if current >= 0 else 0
        self._timeline.select_clip(new_index)

    def _next_clip(self):
        clips = self._timeline.clips
        if not clips:
            return
        current = self._timeline.selected_index
        new_index = min(len(clips) - 1, current + 1) if current >= 0 else 0
        self._timeline.select_clip(new_index)

    def hideEvent(self, event):
        self._player.pause()
        super().hideEvent(event)

    def get_current_clips(self) -> list[EditDecision]:
        return list(self._timeline.clips)
