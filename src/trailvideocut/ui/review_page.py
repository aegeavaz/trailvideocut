import bisect

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
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
    QSpacerItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from trailvideocut.audio.models import AudioAnalysis, MusicSection
from trailvideocut.editor.models import CutPlan, EditDecision
from trailvideocut.ui.timeline import TimelineWidget
from trailvideocut.ui.video_player import VideoPlayer


class ReviewPage(QWidget):
    """Page 2: Timeline review, clip editing, and render settings."""

    back_requested = Signal()
    export_requested = Signal(dict)  # render settings

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio: AudioAnalysis | None = None
        self._sections: list[MusicSection] = []
        self._active_clip_end: float | None = None

        # Preview state
        self._audio_path: str = ""
        self._previewing: bool = False
        self._preview_clip_index: int = -1
        self._preview_decisions: list[EditDecision] = []
        self._preview_target_starts: list[float] = []
        self._music_player: QMediaPlayer | None = None
        self._music_audio_output: QAudioOutput | None = None

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # --- Top navigation ---
        nav = QHBoxLayout()
        btn_back = QPushButton("<< Back to Setup")
        btn_back.clicked.connect(self._on_back)
        self._btn_preview = QPushButton("Preview")
        self._btn_preview.setEnabled(False)
        self._btn_preview.setToolTip("Play clips in sequence synced with music")
        self._btn_preview.clicked.connect(self._toggle_preview)
        self._btn_export = QPushButton("Export >>")
        self._btn_export.setProperty("primary", True)
        self._btn_export.clicked.connect(self._on_export)
        nav.addWidget(btn_back)
        nav.addStretch()
        nav.addWidget(self._btn_preview)
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

        # Preview status label (below timeline, hidden by default)
        self._preview_status = QLabel()
        self._preview_status.setStyleSheet(
            "font-family: monospace; font-size: 13px; color: #4CAF50; padding: 2px 4px;"
        )
        self._preview_status.setVisible(False)
        timeline_layout.addWidget(self._preview_status)

        root.addWidget(timeline_group)

        # --- Main content: video player on top, clip info + settings on bottom ---
        # Video player (stretches to fill available space)
        self._player = VideoPlayer()
        root.addWidget(self._player, stretch=1)

        # Spacing between player controls and bottom section
        root.addSpacerItem(QSpacerItem(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed))

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
        self._transition.setToolTip("Transition style between clips. Crossfade blends clips; hard_cut is instant.")
        render_layout.addRow("Transition:", self._transition)

        self._crossfade_dur = QDoubleSpinBox()
        self._crossfade_dur.setRange(0.0, 2.0)
        self._crossfade_dur.setValue(0.2)
        self._crossfade_dur.setSingleStep(0.05)
        self._crossfade_dur.setToolTip("Duration of crossfade transition in seconds between consecutive clips.")
        render_layout.addRow("Crossfade (s):", self._crossfade_dur)

        self._preset = QComboBox()
        self._preset.addItems(["ultrafast", "superfast", "veryfast", "faster",
                               "fast", "medium", "slow", "slower", "veryslow"])
        self._preset.setCurrentText("veryslow")
        self._preset.setToolTip("FFmpeg encoding speed preset. Slower presets produce better quality at the same file size.")
        render_layout.addRow("Preset:", self._preset)

        self._output_fps = QDoubleSpinBox()
        self._output_fps.setRange(0, 120.0)
        self._output_fps.setValue(0)
        self._output_fps.setSingleStep(1.0)
        self._output_fps.setSpecialValueText("auto (source)")
        self._output_fps.setToolTip("Output frame rate. 0 = use the source video's original frame rate.")
        render_layout.addRow("FPS:", self._output_fps)

        self._threads = QSpinBox()
        self._threads.setRange(0, 64)
        self._threads.setValue(0)
        self._threads.setSpecialValueText("auto")
        self._threads.setToolTip("Number of encoding threads. 0 = auto-detect based on CPU cores.")
        render_layout.addRow("Threads:", self._threads)

        bottom_splitter.addWidget(render_group)
        bottom_splitter.setSizes([350, 250])

        # Fixed-height bottom section (not resizable vertically)
        bottom_splitter.setFixedHeight(200)
        root.addWidget(bottom_splitter, stretch=0)

        # Connect playback cursor, user seek deselection, and clip boundary check
        self._player.position_changed.connect(self._timeline.set_cursor_position)
        self._player.position_changed.connect(self._check_clip_boundary)
        self._player.user_seeked.connect(self._on_user_seeked)

        # Keyboard shortcuts (same as setup page)
        ctx = Qt.WidgetWithChildrenShortcut
        QShortcut(Qt.Key_Space, self, self._on_space, context=ctx)
        QShortcut(Qt.Key_Left, self, self._player._step_back, context=ctx)
        QShortcut(Qt.Key_Right, self, self._player._step_forward, context=ctx)
        QShortcut(Qt.Key_Up, self, self._player._jump_forward, context=ctx)
        QShortcut(Qt.Key_Down, self, self._player._jump_back, context=ctx)
        QShortcut(Qt.Key_Home, self, self._player._go_start, context=ctx)
        QShortcut(Qt.Key_End, self, self._player._go_end, context=ctx)
        QShortcut(Qt.Key_Escape, self, self._stop_preview_if_active, context=ctx)

    def set_data(
        self,
        audio: AudioAnalysis,
        cut_plan: CutPlan,
        video_duration: float,
        video_path: str = "",
        marks: list[float] | None = None,
        audio_path: str = "",
    ):
        self._audio = audio
        self._sections = audio.sections
        self._audio_path = audio_path

        # Enable preview button when audio is available
        self._btn_preview.setEnabled(bool(audio_path))

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

        # Load video
        if video_path:
            self._player.load_video(video_path)

        # Clip info
        self._clip_info.setText("Click a clip on the timeline to see details")

    # --- Preview ---

    def _ensure_music_player(self):
        if self._music_player is not None:
            return
        self._music_player = QMediaPlayer(self)
        self._music_audio_output = QAudioOutput(self)
        self._music_player.setAudioOutput(self._music_audio_output)
        self._music_player.positionChanged.connect(self._on_music_position)
        self._music_player.mediaStatusChanged.connect(self._on_music_status)

    def _toggle_preview(self):
        if self._previewing:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview(self):
        clips = self._timeline.clips
        if not clips or not self._audio_path:
            return

        # Sort decisions by target_start for binary search
        self._preview_decisions = sorted(clips, key=lambda d: d.target_start)
        self._preview_target_starts = [d.target_start for d in self._preview_decisions]
        self._preview_clip_index = -1
        self._previewing = True

        # Mute video player audio (we use the music player for audio)
        self._player.set_muted(True)

        # Disconnect normal playback signals to avoid interference
        self._player.position_changed.disconnect(self._timeline.set_cursor_position)
        self._player.position_changed.disconnect(self._check_clip_boundary)

        # Disable export and timeline interaction during preview
        self._btn_export.setEnabled(False)
        self._timeline.setEnabled(False)

        # Update button
        self._btn_preview.setText("Stop Preview")

        # Show preview status and green cursor
        self._preview_status.setVisible(True)
        self._preview_status.setText("Preview: 00:00 / 00:00")
        self._timeline.set_cursor_color("#4CAF50")

        # Lazy-init and load music
        self._ensure_music_player()
        self._music_player.setSource(QUrl.fromLocalFile(self._audio_path))

        # Seek video to first clip's source position
        first = self._preview_decisions[0]
        self._player.seek_to(first.source_start)

        # Start both players
        self._music_player.play()
        self._player.play()

    def _stop_preview(self):
        if not self._previewing:
            return
        self._previewing = False

        # Stop music, release audio device, pause video, unmute
        if self._music_player is not None:
            self._music_player.stop()
            self._music_player.setSource(QUrl())
        self._player.pause()
        self._player.set_muted(False)

        # Reconnect normal signals
        self._player.position_changed.connect(self._timeline.set_cursor_position)
        self._player.position_changed.connect(self._check_clip_boundary)

        # Re-enable controls
        self._btn_export.setEnabled(True)
        self._timeline.setEnabled(True)

        # Reset UI
        self._btn_preview.setText("Preview")
        self._preview_status.setVisible(False)
        self._timeline.set_cursor_color("#42A5F5")
        self._preview_clip_index = -1
        self._preview_decisions = []
        self._preview_target_starts = []

    def _stop_preview_if_active(self):
        if self._previewing:
            self._stop_preview()

    def _on_music_position(self, music_pos_ms: int):
        if not self._previewing:
            return

        music_pos = music_pos_ms / 1000.0

        # Update preview status label
        total = self._audio.duration if self._audio else 0
        self._preview_status.setText(
            f"Preview: {self._fmt(music_pos)} / {self._fmt(total)}"
        )

        # Find which clip should be playing at this music position
        clip_idx = self._find_clip_for_target(music_pos)

        if clip_idx < 0:
            # In a gap between clips — pause video, let music continue
            if self._player._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            return

        clip = self._preview_decisions[clip_idx]
        offset = music_pos - clip.target_start
        expected_source_pos = clip.source_start + offset

        if clip_idx != self._preview_clip_index:
            # New clip — seek video to correct source position
            self._preview_clip_index = clip_idx
            self._player.seek_to(expected_source_pos)
            self._player.play()
            # Highlight this clip on the timeline
            orig_idx = self._timeline.clips.index(clip) if clip in self._timeline.clips else -1
            if orig_idx >= 0:
                self._timeline._selected = orig_idx
                self._timeline.update()
        else:
            # Same clip — check drift and correct if needed
            current_video_pos = self._player.current_time
            drift = abs(current_video_pos - expected_source_pos)
            if drift > 0.15:
                self._player.seek_to(expected_source_pos)
                self._player.play()

            # Resume video if it was paused (e.g. after a gap)
            if self._player._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self._player.play()

        # Update timeline cursor to expected source position
        self._timeline.set_cursor_position(expected_source_pos)

    def _find_clip_for_target(self, target_time: float) -> int:
        """Binary search for the clip containing target_time. Returns index or -1."""
        if not self._preview_decisions:
            return -1
        idx = bisect.bisect_right(self._preview_target_starts, target_time) - 1
        if idx < 0:
            return -1
        clip = self._preview_decisions[idx]
        if clip.target_start <= target_time < clip.target_end:
            return idx
        return -1

    def _on_music_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._stop_preview()

    # --- Keyboard ---

    def _on_space(self):
        if self._previewing:
            self._stop_preview()
        else:
            self._player.toggle_play()

    def _on_back(self):
        self._stop_preview_if_active()
        self.back_requested.emit()

    # --- Clip interaction ---

    def _on_clip_selected(self, index: int):
        if self._previewing:
            return

        if index < 0 or index >= len(self._timeline.clips):
            self._clip_info.setText("No clip selected")
            self._active_clip_end = None
            return

        clip = self._timeline.clips[index]
        duration = clip.source_end - clip.source_start
        target_dur = clip.target_end - clip.target_start

        # Seek video to clip start and set auto-stop boundary
        self._player.seek_to(clip.source_start)
        self._active_clip_end = clip.source_end

        # Find section
        section_label = "unknown"
        section_energy = 0.0
        mid = (clip.target_start + clip.target_end) / 2
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

    def _on_user_seeked(self):
        if self._previewing:
            self._stop_preview()
            return
        if self._timeline.selected_index >= 0:
            self._timeline.select_clip(-1)

    def _check_clip_boundary(self, position: float):
        if self._previewing:
            return
        if self._active_clip_end is not None and position >= self._active_clip_end:
            self._player.pause()
            self._active_clip_end = None

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
        self._stop_preview_if_active()
        self._player.pause()
        super().hideEvent(event)

    def get_current_clips(self) -> list[EditDecision]:
        return list(self._timeline.clips)

    @staticmethod
    def _fmt(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"
