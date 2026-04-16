import bisect

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QGroupBox,
    QSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSpacerItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from trailvideocut.audio.models import AudioAnalysis, MusicSection
from trailvideocut.editor.models import CutPlan, EditDecision
from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.plate.storage import delete_plates, load_plates, save_plates
from trailvideocut.ui.plate_overlay import PlateOverlayWidget
from trailvideocut.ui.timeline import TimelineWidget
from trailvideocut.ui.video_player import VideoPlayer


class ReviewPage(QWidget):
    """Page 2: Timeline review, clip editing, and render settings."""

    back_requested = Signal()
    export_requested = Signal()

    @property
    def plate_data(self) -> dict[int, "ClipPlateData"]:
        """Plate detection data for all clips."""
        return self._plate_data

    def __init__(self, parent=None):
        super().__init__(parent)
        # Page-scoped shortcuts use Qt.WidgetWithChildrenShortcut and the
        # `_restore_keyboard_focus` helper calls `self.setFocus()`; the page
        # itself must accept focus for either to work.
        self.setFocusPolicy(Qt.StrongFocus)
        self._audio: AudioAnalysis | None = None
        self._sections: list[MusicSection] = []
        self._active_clip_end: float | None = None

        # Preview state
        self._audio_path: str = ""
        self._video_path: str = ""
        self._base_summary: str = ""
        self._previewing: bool = False
        self._preview_clip_index: int = -1
        self._preview_decisions: list[EditDecision] = []
        self._preview_target_starts: list[float] = []
        self._music_player: QMediaPlayer | None = None
        self._music_audio_output: QAudioOutput | None = None

        # Plate detection state
        self._plate_data: dict[int, ClipPlateData] = {}  # clip_index -> ClipPlateData
        self._plate_worker = None
        self._video_dims: tuple[int, int] | None = None  # (width, height)
        self._plate_list_updating: bool = False  # guard against selection loops
        self._cached_detector = None  # lazily cached PlateDetector
        self._cached_detector_settings: tuple | None = None  # settings fingerprint
        self._pending_frame_detect: bool = False  # flag for post-download frame detect
        self._blur_preview_timer: QTimer | None = None  # throttle blur preview updates
        self._plate_list_refresh_timer: QTimer | None = None  # coalesce chip rebuilds during scrub

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # --- Top navigation ---
        nav = QHBoxLayout()
        btn_back = QPushButton("<< Back to Setup")
        btn_back.clicked.connect(self._on_back)
        self._btn_preview = QPushButton("Preview Mode")
        self._btn_preview.setEnabled(False)
        self._btn_preview.setToolTip("Enter preview mode to play clips synced with music using player controls")
        self._btn_preview.clicked.connect(self._toggle_preview)

        self._btn_export = QPushButton("Export >>")
        self._btn_export.setProperty("primary", True)
        self._btn_export.clicked.connect(self._on_export)
        nav.addWidget(btn_back)
        nav.addStretch()
        nav.addWidget(self._btn_preview)
        nav.addWidget(self._btn_export)
        root.addLayout(nav)

        # --- Summary + selected clip info ---
        summary_row = QHBoxLayout()
        self._summary = QLabel()
        self._summary.setProperty("name", "heading")
        self._summary.setStyleSheet("font-size: 13px; color: #ccc; padding: 4px;")
        summary_row.addWidget(self._summary)
        summary_row.addStretch()
        self._clip_info_label = QLabel()
        self._clip_info_label.setStyleSheet(
            "font-family: monospace; font-size: 13px; color: #ccc; padding: 4px;"
        )
        summary_row.addWidget(self._clip_info_label)
        root.addLayout(summary_row)

        # --- Timeline ---
        timeline_group = QGroupBox("Source Video Timeline")
        timeline_layout = QVBoxLayout(timeline_group)
        timeline_layout.setContentsMargins(2, 2, 2, 2)
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

        timeline_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root.addWidget(timeline_group)

        # --- Main content: video player on top, clip info + settings on bottom ---
        # Video player (stretches to fill available space)
        self._player = VideoPlayer()
        self._player.set_invert_wheel(True)  # plain wheel zooms, Ctrl+wheel seeks
        root.addWidget(self._player, stretch=1)

        # Plate overlay — top-level frameless window that floats above the
        # QVideoWidget's native Direct3D surface on Windows.
        self._plate_overlay = PlateOverlayWidget(self._player)
        self._plate_overlay.hide()
        self._plate_overlay.unexpectedly_hidden.connect(
            self._on_overlay_unexpectedly_hidden,
        )
        self._plate_overlay.selection_changed.connect(self._on_plate_selection_changed)
        self._plate_overlay.box_changed.connect(self._on_plate_box_changed)
        self._plate_overlay.add_plate_requested.connect(self._on_add_plate)

        # Spacing between player controls and bottom section
        root.addSpacerItem(QSpacerItem(0, 12, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # Plate detection settings & info
        plate_group = QGroupBox("Plate Detection")
        plate_group.setStyleSheet(
            "QGroupBox { margin-top: 4px; padding-top: 14px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        plate_layout = QVBoxLayout(plate_group)
        plate_layout.setSpacing(4)

        # Row 1: All action buttons in one row
        btn_row = QHBoxLayout()
        self._btn_detect_plates = QPushButton("Detect Plates")
        self._btn_detect_plates.setEnabled(False)
        self._btn_detect_plates.setToolTip(
            "Detect license plates in the selected clip, or all clips if none is selected"
        )
        self._btn_detect_plates.clicked.connect(self._on_detect_plates)
        btn_row.addWidget(self._btn_detect_plates)

        self._btn_detect_frame = QPushButton("Detect Frame")
        self._btn_detect_frame.setEnabled(False)
        self._btn_detect_frame.setToolTip(
            "Re-run plate detection on the current frame only"
        )
        self._btn_detect_frame.clicked.connect(self._on_detect_frame)
        btn_row.addWidget(self._btn_detect_frame)

        self._btn_add_plate = QPushButton("Add Plate")
        self._btn_add_plate.setEnabled(False)
        self._btn_add_plate.setToolTip("Add a manual plate box at the current frame")
        self._btn_add_plate.clicked.connect(self._on_add_plate)
        btn_row.addWidget(self._btn_add_plate)

        self._btn_clear_clip_plates = QPushButton("Clear Clip Plates")
        self._btn_clear_clip_plates.setEnabled(False)
        self._btn_clear_clip_plates.setToolTip(
            "Delete all plates (detected and manual) in the selected clip"
        )
        self._btn_clear_clip_plates.clicked.connect(self._on_clear_clip_plates)
        btn_row.addWidget(self._btn_clear_clip_plates)

        self._btn_clear_frame_plates = QPushButton("Clear Frame Plates")
        self._btn_clear_frame_plates.setEnabled(False)
        self._btn_clear_frame_plates.setToolTip(
            "Delete all plates (detected and manual) in the current frame"
        )
        self._btn_clear_frame_plates.clicked.connect(self._on_clear_frame_plates)
        btn_row.addWidget(self._btn_clear_frame_plates)

        self._chk_show_plates = QCheckBox("Show Plates")
        self._chk_show_plates.setChecked(True)
        self._chk_show_plates.setEnabled(False)
        self._chk_show_plates.toggled.connect(self._on_toggle_plates_visible)
        btn_row.addWidget(self._chk_show_plates)

        plate_layout.addLayout(btn_row)

        # Row 2: All detection settings in one row
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Confidence:"))
        self._spin_confidence = QDoubleSpinBox()
        self._spin_confidence.setRange(0.01, 1.0)
        self._spin_confidence.setValue(0.05)
        self._spin_confidence.setSingleStep(0.05)
        self._spin_confidence.setToolTip("Minimum confidence threshold for plate detection")
        settings_row.addWidget(self._spin_confidence)

        self._chk_exclude_phones = QCheckBox("Exclude Phone")
        self._chk_exclude_phones.setChecked(True)
        self._chk_exclude_phones.setToolTip("Exclude detected phone/device regions from plate results")
        settings_row.addWidget(self._chk_exclude_phones)

        settings_row.addWidget(QLabel("Gap:"))
        self._spin_phone_gap = QSpinBox()
        self._spin_phone_gap.setRange(5, 120)
        self._spin_phone_gap.setValue(30)
        self._spin_phone_gap.setSingleStep(5)
        self._spin_phone_gap.setToolTip("Re-detect phone every N frames (lower = more accurate, slower)")
        settings_row.addWidget(self._spin_phone_gap)
        self._chk_exclude_phones.toggled.connect(self._spin_phone_gap.setEnabled)

        self._chk_debug_plates = QCheckBox("Debug")
        self._chk_debug_plates.setToolTip("Print plate detection debug info to the console")
        settings_row.addWidget(self._chk_debug_plates)

        settings_row.addWidget(QLabel("Min Ratio:"))
        self._spin_min_ratio = QDoubleSpinBox()
        self._spin_min_ratio.setRange(0.5, 5.0)
        self._spin_min_ratio.setValue(0.5)
        self._spin_min_ratio.setSingleStep(0.1)
        self._spin_min_ratio.setToolTip("Minimum width/height aspect ratio for plate geometry filter")
        settings_row.addWidget(self._spin_min_ratio)

        settings_row.addWidget(QLabel("Max Ratio:"))
        self._spin_max_ratio = QDoubleSpinBox()
        self._spin_max_ratio.setRange(0.5, 10.0)
        self._spin_max_ratio.setValue(2.0)
        self._spin_max_ratio.setSingleStep(0.1)
        self._spin_max_ratio.setToolTip("Maximum width/height aspect ratio for plate geometry filter")
        settings_row.addWidget(self._spin_max_ratio)

        settings_row.addWidget(QLabel("Min W px:"))
        self._spin_min_w = QSpinBox()
        self._spin_min_w.setRange(1, 200)
        self._spin_min_w.setValue(10)
        self._spin_min_w.setToolTip("Minimum plate width in pixels")
        settings_row.addWidget(self._spin_min_w)

        settings_row.addWidget(QLabel("Min H px:"))
        self._spin_min_h = QSpinBox()
        self._spin_min_h.setRange(1, 200)
        self._spin_min_h.setValue(5)
        self._spin_min_h.setToolTip("Minimum plate height in pixels")
        settings_row.addWidget(self._spin_min_h)

        settings_row.addWidget(QLabel("Min Track:"))
        self._spin_min_track = QSpinBox()
        self._spin_min_track.setRange(1, 30)
        self._spin_min_track.setValue(1)
        self._spin_min_track.setToolTip("Minimum consecutive frames a plate must appear in to be kept")
        settings_row.addWidget(self._spin_min_track)

        plate_layout.addLayout(settings_row)

        # Row 3: Plate chips (horizontal scrollable, like marks list)
        self._plate_chips_scroll = QScrollArea()
        self._plate_chips_scroll.setWidgetResizable(True)
        self._plate_chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._plate_chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._plate_chips_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._plate_chips_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._plate_chips_container = QWidget()
        self._plate_chips_layout = QHBoxLayout(self._plate_chips_container)
        self._plate_chips_layout.setContentsMargins(0, 0, 0, 0)
        self._plate_chips_layout.setSpacing(6)
        self._plate_chips_layout.addStretch()
        self._plate_chips_scroll.setWidget(self._plate_chips_container)
        plate_layout.addWidget(self._plate_chips_scroll)

        # Row 4: Persistence, blur preview, and progress controls
        controls_row = QHBoxLayout()
        self._btn_clear_plates = QPushButton("Clear Saved Plates")
        self._btn_clear_plates.setEnabled(False)
        self._btn_clear_plates.setToolTip("Delete saved plate data from disk and clear all detections")
        self._btn_clear_plates.clicked.connect(self._on_clear_plates)
        controls_row.addWidget(self._btn_clear_plates)

        self._lbl_plate_status = QLabel()
        self._lbl_plate_status.setStyleSheet("font-size: 11px; color: #4CAF50;")
        controls_row.addWidget(self._lbl_plate_status)

        self._btn_preview_blur = QPushButton("Preview Blur")
        self._btn_preview_blur.setCheckable(True)
        self._btn_preview_blur.setEnabled(False)
        self._btn_preview_blur.setToolTip("Toggle blur preview on the video overlay")
        self._btn_preview_blur.toggled.connect(self._on_toggle_blur_preview)
        controls_row.addWidget(self._btn_preview_blur)

        controls_row.addStretch()

        self._plate_progress_bar = QProgressBar()
        self._plate_progress_bar.setTextVisible(True)
        self._plate_progress_bar.setMaximumHeight(20)
        self._plate_progress_bar.setFormat("")
        self._plate_progress_bar.setValue(0)
        self._btn_cancel_detect = QPushButton("Cancel")
        self._btn_cancel_detect.setEnabled(False)
        self._btn_cancel_detect.clicked.connect(self._on_cancel_detect)
        controls_row.addWidget(self._plate_progress_bar, stretch=1)
        controls_row.addWidget(self._btn_cancel_detect)
        plate_layout.addLayout(controls_row)

        plate_group.setFixedHeight(190)
        root.addWidget(plate_group, stretch=0)

        # Connect playback cursor, user seek deselection, and clip boundary check
        self._player.position_changed.connect(self._timeline.set_cursor_position)
        self._player.position_changed.connect(self._check_clip_boundary)
        self._player.position_changed.connect(self._update_plate_overlay_frame)
        self._player.user_seeked.connect(self._on_user_seeked)
        self._player.zoom_changed.connect(self._on_zoom_changed)

        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_changed)

        # Keyboard shortcuts (same as setup page)
        ctx = Qt.WidgetWithChildrenShortcut
        QShortcut(Qt.Key_Space, self, self._on_space, context=ctx)
        sc_left = QShortcut(Qt.Key_Left, self, self._on_step_back_pressed, context=ctx)
        sc_left.setAutoRepeat(False)
        sc_right = QShortcut(Qt.Key_Right, self, self._on_step_forward_pressed, context=ctx)
        sc_right.setAutoRepeat(False)
        QShortcut(Qt.Key_Up, self, self._player._jump_forward, context=ctx)
        QShortcut(Qt.Key_Down, self, self._player._jump_back, context=ctx)
        QShortcut(Qt.Key_Home, self, self._player._go_start, context=ctx)
        QShortcut(Qt.Key_End, self, self._player._go_end, context=ctx)
        QShortcut(Qt.Key_Escape, self, self._stop_preview_if_active, context=ctx)
        QShortcut(Qt.Key_Delete, self, self._on_delete_key, context=ctx)
        QShortcut(Qt.Key_Backspace, self, self._on_delete_key, context=ctx)

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
        self._video_path = video_path

        # Enable preview button when audio is available
        self._btn_preview.setEnabled(bool(audio_path))

        # Enable plate detection button when clips are available
        self._btn_detect_plates.setEnabled(bool(cut_plan.decisions))

        # Summary
        self._base_summary = (
            f"Tempo: {audio.tempo:.0f} BPM  |  "
            f"Beats: {len(audio.beats)}  |  "
            f"Clips: {len(cut_plan.decisions)}  |  "
            f"CV: {cut_plan.score_cv:.3f}  |  "
            f"Duration: {audio.duration:.1f}s"
        )
        self._summary.setText(self._base_summary)

        # Timeline
        self._timeline.set_data(cut_plan.decisions, video_duration)

        # Marks on timeline and player
        if marks:
            self._timeline.set_marks(marks)
            self._player.set_marks(marks)

        # Load video
        if video_path:
            self._player.load_video(video_path)

        # Auto-load persisted plate data
        self._plate_data = {}
        self._lbl_plate_status.setText("")
        if video_path and cut_plan.decisions:
            valid_indices = set(range(len(cut_plan.decisions)))
            loaded = load_plates(video_path, valid_clip_indices=valid_indices)
            if loaded:
                self._plate_data = loaded
                self._chk_show_plates.setEnabled(True)
                self._btn_add_plate.setEnabled(True)
                self._btn_clear_plates.setEnabled(True)
                self._lbl_plate_status.setText("Plates loaded from disk")
                self._lbl_plate_status.setStyleSheet("")
                self._plate_overlay.setVisible(self._chk_show_plates.isChecked())
                self._sync_overlay_to_current_clip()

    # --- Preview Mode ---

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
            self._exit_preview_mode()
        else:
            self._enter_preview_mode()

    def _enter_preview_mode(self):
        """Enter preview mode without auto-playing."""
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
        try:
            self._player.position_changed.disconnect(self._timeline.set_cursor_position)
        except RuntimeError:
            pass
        try:
            self._player.position_changed.disconnect(self._check_clip_boundary)
        except RuntimeError:
            pass

        # Set transport callback and external control on VideoPlayer
        self._player.set_transport_callback(self._handle_transport)
        self._player.set_external_control(True)

        # Set slider to audio duration
        audio_duration_ms = int(self._audio.duration * 1000) if self._audio else 0
        self._player.set_slider_range_ms(audio_duration_ms)
        self._player.set_slider_position_ms(0)
        self._player.update_time_label_external(0.0, self._audio.duration if self._audio else 0.0)

        # Disable export during preview, but keep timeline enabled
        self._btn_export.setEnabled(False)

        # Update button appearance
        self._btn_preview.setText("Exit Preview")
        self._btn_preview.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold;"
        )

        # Show preview status and green cursor
        self._preview_status.setVisible(True)
        self._preview_status.setText("Preview Mode — paused")
        self._timeline.set_cursor_color("#4CAF50")

        # Lazy-init and load music (but don't play yet)
        self._ensure_music_player()
        self._music_player.setSource(QUrl.fromLocalFile(self._audio_path))

        # Seek video to first clip's source position, paused
        first = self._preview_decisions[0]
        self._player.seek_to(first.source_start)
        self._player.pause()

        # Show first clip info
        orig_idx = self._timeline.clips.index(first) if first in self._timeline.clips else 0
        self._timeline._selected = orig_idx
        self._timeline.update()
        self._show_clip_info(orig_idx)

    def _exit_preview_mode(self):
        """Exit preview mode and restore normal controls."""
        if not self._previewing:
            return
        self._previewing = False

        # Stop music, release audio device
        if self._music_player is not None:
            self._music_player.stop()
            self._music_player.setSource(QUrl())

        # Pause video, unmute
        self._player.pause()
        self._player.set_muted(False)

        # Clear transport callback and external control
        self._player.set_transport_callback(None)
        self._player.set_external_control(False)

        # Restore slider to video duration
        self._player.restore_slider_range()

        # Reconnect normal signals (safe with try/except)
        self._player.position_changed.connect(self._timeline.set_cursor_position)
        self._player.position_changed.connect(self._check_clip_boundary)

        # Re-enable controls
        self._btn_export.setEnabled(True)

        # Reset UI
        self._btn_preview.setText("Preview Mode")
        self._btn_preview.setStyleSheet("")
        self._preview_status.setVisible(False)
        self._timeline.set_cursor_color("#42A5F5")
        self._preview_clip_index = -1
        self._preview_decisions = []
        self._preview_target_starts = []

    def _stop_preview_if_active(self):
        if self._previewing:
            self._exit_preview_mode()

    # --- Preview transport ---

    def _handle_transport(self, action: str, *args):
        """Dispatch transport actions to preview methods."""
        if action == "toggle_play":
            self._preview_toggle_play()
        elif action == "go_start":
            self._preview_go_start()
        elif action == "go_end":
            self._preview_go_end()
        elif action == "jump_forward":
            self._preview_jump(5000)
        elif action == "jump_back":
            self._preview_jump(-5000)
        elif action == "step_forward":
            self._preview_step_frame(+1)
        elif action == "step_back":
            self._preview_step_frame(-1)
        elif action in ("seek", "slider_moved"):
            self._preview_seek_ms(args[0])
        elif action == "wheel":
            self._preview_step(args[0])

    def _preview_toggle_play(self):
        """Toggle play/pause for both music and video."""
        if self._music_player is None:
            return
        if self._music_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._music_player.pause()
            self._player.pause()
        else:
            self._music_player.play()
            # Video play is managed by _on_music_position when it finds the right clip

    def _preview_go_start(self):
        if self._music_player:
            self._music_player.setPosition(0)
            self._on_music_position(0)

    def _preview_go_end(self):
        if self._music_player and self._audio:
            end_ms = max(0, int(self._audio.duration * 1000) - 100)
            self._music_player.setPosition(end_ms)
            self._on_music_position(end_ms)

    def _preview_jump(self, delta_ms: int):
        if self._music_player and self._audio:
            current = self._music_player.position()
            total = int(self._audio.duration * 1000)
            new_pos = max(0, min(current + delta_ms, total))
            self._music_player.setPosition(new_pos)
            self._on_music_position(new_pos)

    def _preview_step(self, delta_ms: int):
        if self._music_player and self._audio:
            current = self._music_player.position()
            total = int(self._audio.duration * 1000)
            new_pos = max(0, min(current + delta_ms, total))
            self._music_player.setPosition(new_pos)
            self._on_music_position(new_pos)

    def _preview_step_frame(self, direction: int):
        """Advance music position by exactly one video-frame duration."""
        if not (self._music_player and self._audio):
            return
        current_ms = self._music_player.position()
        current_frame = self._player.frame_at(current_ms / 1000.0)
        target_ms = self._player.frame_to_ms(current_frame + direction)
        total = int(self._audio.duration * 1000)
        new_pos = max(0, min(target_ms, total))
        self._music_player.setPosition(new_pos)
        self._on_music_position(new_pos)

    def _preview_seek_ms(self, position_ms: int):
        if self._music_player:
            self._music_player.setPosition(position_ms)
            self._on_music_position(position_ms)

    # --- Music sync ---

    def _on_music_position(self, music_pos_ms: int):
        if not self._previewing:
            return

        music_pos = music_pos_ms / 1000.0
        total = self._audio.duration if self._audio else 0
        music_playing = (
            self._music_player is not None
            and self._music_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )

        # Update preview status label
        state = "playing" if music_playing else "paused"
        self._preview_status.setText(
            f"Preview Mode — {state} — {self._fmt(music_pos)} / {self._fmt(total)}"
        )

        # Update slider and time label on the VideoPlayer
        self._player.set_slider_position_ms(music_pos_ms)
        self._player.update_time_label_external(music_pos, total)

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
            if music_playing:
                self._player.play()

            # Highlight this clip on the timeline and show its info
            orig_idx = self._timeline.clips.index(clip) if clip in self._timeline.clips else -1
            if orig_idx >= 0:
                self._timeline._selected = orig_idx
                self._timeline.update()
                self._show_clip_info(orig_idx)
        else:
            # Same clip — check drift and correct if needed. 35 ms is ≈1 frame
            # at 30 fps; anything looser leaves audible lag between the video
            # cut and the corresponding music beat.
            current_video_pos = self._player.current_time
            drift = abs(current_video_pos - expected_source_pos)
            if drift > 0.035 or not music_playing:
                self._player.seek_to(expected_source_pos)
                if music_playing:
                    self._player.play()

            # Resume video if it was paused (e.g. after a gap) and music is playing
            if music_playing and self._player._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
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
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._previewing:
            # Stay in preview mode — user can seek back
            self._player.pause()
            self._preview_status.setText("Preview Mode — finished")

    # --- Keyboard ---

    def _on_space(self):
        if self._previewing:
            self._preview_toggle_play()
        else:
            self._player.toggle_play()

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

    def _on_back(self):
        self._stop_preview_if_active()
        self.back_requested.emit()

    # --- Clip interaction ---

    def _show_clip_info(self, index: int):
        """Update the Selected Clip panel for clip at index."""
        if index < 0 or index >= len(self._timeline.clips):
            self._clip_info_label.setText("")
            return

        clip = self._timeline.clips[index]
        duration = clip.source_end - clip.source_start
        target_dur = clip.target_end - clip.target_start

        # Find section
        section_label = "unknown"
        section_energy = 0.0
        mid = (clip.target_start + clip.target_end) / 2
        for sec in self._sections:
            if sec.start_time <= mid < sec.end_time:
                section_label = sec.label
                section_energy = sec.energy
                break

        # Plate detection info
        plate_info = ""
        if index in self._plate_data:
            pd = self._plate_data[index]
            frames_with_plates = len(pd.detections)
            total_boxes = sum(len(boxes) for boxes in pd.detections.values())
            manual_boxes = sum(
                1 for boxes in pd.detections.values() for b in boxes if b.manual
            )
            plate_info = f"  Plates: {total_boxes} in {frames_with_plates}f"
            if manual_boxes:
                plate_info += f" ({manual_boxes}m)"

        self._clip_info_label.setText(
            f"Clip {index + 1}/{len(self._timeline.clips)}"
            f"  Score: {clip.interest_score:.3f}"
            f"  Section: {section_label} ({section_energy:.2f})"
            f"{plate_info}"
            f"  Src: {clip.source_start:.2f}-{clip.source_end:.2f}s ({duration:.2f}s)"
            f"  Tgt: {clip.target_start:.2f}-{clip.target_end:.2f}s ({target_dur:.2f}s)"
        )

    def _on_clip_selected(self, index: int):
        if self._previewing:
            if 0 <= index < len(self._timeline.clips):
                clip = self._timeline.clips[index]
                # Pre-set preview clip index so later positionChanged won't re-seek
                if clip in self._preview_decisions:
                    self._preview_clip_index = self._preview_decisions.index(clip)
                # Seek video directly to clip source start
                self._player.seek_to(clip.source_start)
                self._timeline.set_cursor_position(clip.source_start)
                self._show_clip_info(index)
                # Block signals during setPosition to prevent positionChanged
                # from firing with stale/intermediate positions that would
                # cause _on_music_position to seek to the wrong clip.
                if self._music_player:
                    self._music_player.blockSignals(True)
                    self._music_player.setPosition(int(clip.target_start * 1000))
                    self._music_player.blockSignals(False)
            return

        if index < 0 or index >= len(self._timeline.clips):
            self._clip_info_label.setText("")
            self._active_clip_end = None
            return

        clip = self._timeline.clips[index]

        # Seek video to clip start and set auto-stop boundary
        self._player.seek_to(clip.source_start)
        self._active_clip_end = clip.source_end
        self._show_clip_info(index)

        # Update plate overlay for the selected clip
        self._sync_overlay_to_current_clip()

    def _on_user_seeked(self):
        if self._previewing:
            return  # Transport callback handles this; should not fire
        self._select_clip_at_position()

    def _select_clip_at_position(self):
        """Select the clip containing the current playback position, or deselect."""
        current_time = self._player.current_time
        clips = self._timeline.clips
        for i, clip in enumerate(clips):
            if clip.source_start <= current_time < clip.source_end:
                if self._timeline.selected_index != i:
                    self._timeline._selected = i
                    self._timeline.update()
                    self._show_clip_info(i)
                    self._sync_overlay_to_current_clip()
                return
        # Position is not within any clip — deselect
        if self._timeline.selected_index >= 0:
            self._timeline._selected = -1
            self._timeline.update()
            self._clip_info_label.setText("")
            self._active_clip_end = None

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
        self.export_requested.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._plate_overlay.isVisible():
            self._position_overlay()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._plate_overlay.isVisible():
            self._position_overlay()

    def _on_app_state_changed(self, state):
        if state == Qt.ApplicationActive and self._plate_overlay.isVisible():
            self._plate_overlay.raise_()
            self._position_overlay()

    def hideEvent(self, event):
        self._plate_overlay.hide()
        self._stop_preview_if_active()
        self._player.pause()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._plate_data and self._chk_show_plates.isChecked():
            self._plate_overlay.show()
            self._position_overlay()

    def get_current_clips(self) -> list[EditDecision]:
        return list(self._timeline.clips)

    @staticmethod
    def _fmt(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    # --- Plate Detection ---

    def _on_detect_plates(self):
        """Start plate detection on selected clip or all clips."""
        from trailvideocut.plate.model_manager import get_model_path

        clips = self._timeline.clips
        if not clips or not self._video_path:
            if self._chk_debug_plates.isChecked():
                print(f"[PlateDetect] No data: clips={len(clips) if clips else 0}, "
                      f"video_path='{self._video_path}'")
            QMessageBox.warning(
                self, "Cannot Detect Plates",
                "No video or clips available. Run analysis first.",
            )
            return

        # Check if model is already cached
        model_path = get_model_path()
        if model_path is not None:
            if self._chk_debug_plates.isChecked():
                print(f"[PlateDetect] Model found at {model_path}")
            self._start_plate_detection(str(model_path))
            return

        # Model not cached — download it
        if self._chk_debug_plates.isChecked():
            print("[PlateDetect] Model not found, starting download...")
        self._start_model_download()

    def _start_model_download(self):
        """Download the plate detection model with a progress dialog."""
        from trailvideocut.ui.workers import ModelDownloadWorker

        self._download_dialog = QProgressDialog(
            "Downloading plate detection model...", "Cancel", 0, 100, self,
        )
        self._download_dialog.setWindowTitle("Model Download")
        self._download_dialog.setMinimumWidth(400)
        self._download_dialog.setAutoClose(False)
        self._download_dialog.setAutoReset(False)

        self._download_worker = ModelDownloadWorker(parent=self)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)

        self._download_dialog.canceled.connect(self._download_worker.terminate)
        self._download_dialog.show()
        self._download_worker.start()

    def _on_download_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded * 100 / total)
            self._download_dialog.setValue(pct)
            mb_done = downloaded / 1_048_576
            mb_total = total / 1_048_576
            self._download_dialog.setLabelText(
                f"Downloading plate detection model... {mb_done:.1f} / {mb_total:.1f} MB"
            )

    def _on_download_finished(self, model_path: str):
        if self._chk_debug_plates.isChecked():
            print(f"[PlateDetect] Model downloaded to {model_path}")
        self._download_dialog.close()
        self._download_dialog = None
        self._download_worker = None
        if self._pending_frame_detect:
            self._pending_frame_detect = False
            self._run_single_frame_detection(model_path)
        else:
            self._start_plate_detection(model_path)

    def _on_download_error(self, message: str):
        if self._chk_debug_plates.isChecked():
            print(f"[PlateDetect] Download error: {message}")
        self._download_dialog.close()
        self._download_dialog = None
        self._download_worker = None
        self._pending_frame_detect = False
        QMessageBox.critical(
            self, "Model Download Failed",
            f"Could not download the plate detection model:\n\n{message}",
        )

    def _start_plate_detection(self, model_path: str):
        """Launch plate detection worker with the given model."""
        from trailvideocut.ui.workers import PlateDetectionWorker

        clips = self._timeline.clips
        selected = self._timeline.selected_index
        if 0 <= selected < len(clips):
            clip = clips[selected]
            clip_list = [(selected, clip.source_start, clip.source_end)]
        else:
            clip_list = [
                (i, c.source_start, c.source_end) for i, c in enumerate(clips)
            ]

        # Activate progress UI
        self._plate_progress_bar.setValue(0)
        self._plate_progress_bar.setFormat("Detecting plates...")
        self._btn_cancel_detect.setEnabled(True)
        self._btn_detect_plates.setEnabled(False)
        self._btn_detect_frame.setEnabled(False)
        self._btn_clear_clip_plates.setEnabled(False)
        self._btn_clear_frame_plates.setEnabled(False)

        # Launch worker
        self._plate_worker = PlateDetectionWorker(
            video_path=self._video_path,
            clips=clip_list,
            model_path=model_path,
            confidence_threshold=self._spin_confidence.value(),
            exclude_phones=self._chk_exclude_phones.isChecked(),
            phone_redetect_every=self._spin_phone_gap.value(),
            debug=self._chk_debug_plates.isChecked(),
            min_ratio=self._spin_min_ratio.value(),
            max_ratio=self._spin_max_ratio.value(),
            min_plate_px_w=self._spin_min_w.value(),
            min_plate_px_h=self._spin_min_h.value(),
            min_track_length=self._spin_min_track.value(),
            parent=self,
        )
        self._plate_worker.progress.connect(self._on_plate_progress)
        self._plate_worker.finished.connect(self._on_plate_finished)
        self._plate_worker.error.connect(self._on_plate_error)
        self._plate_worker.start()

    def _on_cancel_detect(self):
        if self._plate_worker is not None:
            self._plate_worker.stop()

    def _on_plate_progress(self, clip_index: int, frame: int, total: int):
        clips = self._timeline.clips
        total_clips = len(clips)
        self._plate_progress_bar.setMaximum(total)
        self._plate_progress_bar.setValue(frame)
        self._plate_progress_bar.setFormat(
            f"Detecting plates: clip {clip_index + 1}/{total_clips}, "
            f"frame {frame}/{total}"
        )

    def _on_plate_finished(self, results: dict):
        """Handle completed plate detection."""
        # Merge results, preserving manual boxes from re-detection
        for clip_idx, new_data in results.items():
            if clip_idx in self._plate_data:
                existing = self._plate_data[clip_idx]
                # Preserve manual boxes from all frames
                manual_boxes: dict[int, list[PlateBox]] = {}
                for frame, boxes in existing.detections.items():
                    manuals = [b for b in boxes if b.manual]
                    if manuals:
                        manual_boxes[frame] = manuals
                # Start from new detections and merge manuals back
                for frame, manuals in manual_boxes.items():
                    if frame in new_data.detections:
                        new_data.detections[frame].extend(manuals)
                    else:
                        new_data.detections[frame] = manuals

            self._plate_data[clip_idx] = new_data

        # Persist to disk
        self._save_plates()

        # Log detection summary
        if self._chk_debug_plates.isChecked():
            for clip_idx, data in results.items():
                frames = sorted(data.detections.keys())
                total = sum(len(b) for b in data.detections.values())
                frame_range = f"{frames[0]}-{frames[-1]}" if frames else "none"
                print(f"[PlateDetect] Clip {clip_idx}: {total} boxes in "
                      f"{len(frames)} frames (range: {frame_range})")

        # Reset progress, re-enable button
        self._plate_progress_bar.setValue(0)
        self._plate_progress_bar.setFormat("")
        self._btn_cancel_detect.setEnabled(False)
        self._btn_detect_plates.setEnabled(True)

        # Enable plate UI
        self._chk_show_plates.setEnabled(True)
        self._btn_add_plate.setEnabled(True)
        self._btn_clear_plates.setEnabled(True)
        self._plate_overlay.setVisible(self._chk_show_plates.isChecked())

        # Update overlay for current frame
        self._sync_overlay_to_current_clip()

        self._plate_worker = None
        self._update_frame_buttons()

    def _on_plate_error(self, message: str):
        if self._chk_debug_plates.isChecked():
            print(f"[PlateDetect] Error: {message}")
        self._plate_progress_bar.setValue(0)
        self._plate_progress_bar.setFormat("")
        self._btn_cancel_detect.setEnabled(False)
        self._btn_detect_plates.setEnabled(True)
        self._plate_worker = None
        self._update_frame_buttons()
        QMessageBox.critical(
            self, "Plate Detection Error",
            f"An error occurred during plate detection:\n\n{message}",
        )

    def _on_toggle_plates_visible(self, visible: bool):
        show = visible and bool(self._plate_data)
        self._plate_overlay.setVisible(show)
        self._btn_add_plate.setEnabled(show)
        if show:
            self._position_overlay()

    def _sync_overlay_to_current_clip(self):
        """Set the overlay's clip data based on the currently selected/active clip."""
        self._ensure_video_dims()
        clip_data = None

        selected = self._timeline.selected_index
        if selected >= 0 and selected in self._plate_data:
            clip_data = self._plate_data[selected]
        else:
            # Find clip for current video position
            current_time = self._player.current_time
            clips = self._timeline.clips
            for i, clip in enumerate(clips):
                if clip.source_start <= current_time <= clip.source_end:
                    if i in self._plate_data:
                        clip_data = self._plate_data[i]
                    break

        self._plate_overlay.set_clip_data(clip_data)

        # Set geometry and current frame immediately so boxes are visible now
        self._position_overlay()
        frame_num = self._player.frame_at(self._player.current_time)
        self._plate_overlay.set_current_frame(frame_num, force=True)
        self._refresh_plate_list()
        self._update_frame_buttons()

    def _ensure_video_dims(self):
        """Cache and set video dimensions on the overlay."""
        if self._video_dims is None and self._video_path:
            import cv2
            cap = cv2.VideoCapture(self._video_path)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            self._video_dims = (w, h)
        if self._video_dims:
            self._plate_overlay.set_video_size(*self._video_dims)

    def _position_overlay(self):
        """Position the overlay as a top-level window over the video display area."""
        display = self._player.video_widget
        if not display.isVisible():
            return
        global_pos = display.mapToGlobal(display.rect().topLeft())
        self._plate_overlay.setGeometry(
            global_pos.x(), global_pos.y(), display.width(), display.height(),
        )
        self._update_overlay_effective_rect()

    def _on_zoom_changed(self, zoom: float):
        """Update overlay's effective video rect and zoom state when zoom/pan changes."""
        self._plate_overlay.set_zoom(zoom)
        if self._plate_overlay.isVisible():
            self._update_overlay_effective_rect()

    def _update_overlay_effective_rect(self):
        """Compute and set the effective video rect on the overlay."""
        eff = self._player.get_effective_video_rect()
        if eff.isEmpty():
            self._plate_overlay.set_effective_video_rect(None)
        else:
            self._plate_overlay.set_effective_video_rect(eff)

    def _on_overlay_unexpectedly_hidden(self):
        """Restore the overlay if it was hidden by the window manager."""
        if self._chk_show_plates.isChecked() and self._plate_data and self.isVisible():
            QTimer.singleShot(0, self._restore_overlay)

    def _restore_overlay(self):
        if self._chk_show_plates.isChecked() and self._plate_data and self.isVisible():
            self._plate_overlay.show()
            self._position_overlay()
            self._plate_overlay.raise_()

    def _schedule_plate_list_refresh(self):
        """Coalesce chip rebuilds so rapid scrubbing doesn't thrash the UI."""
        if self._plate_list_refresh_timer is None:
            self._plate_list_refresh_timer = QTimer(self)
            self._plate_list_refresh_timer.setSingleShot(True)
            self._plate_list_refresh_timer.setInterval(100)
            self._plate_list_refresh_timer.timeout.connect(self._refresh_plate_list)
        self._plate_list_refresh_timer.start()

    def _refresh_plate_list(self):
        """Populate the plate chips with all boxes in the current frame."""
        self._plate_list_updating = True
        try:
            # Clear existing chips
            while self._plate_chips_layout.count():
                item = self._plate_chips_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            chip_style = (
                "QPushButton { border-radius: 12px; padding: 4px 10px;"
                " font-family: monospace; font-size: 11px;"
                " background: #3a3a3a; color: #ccc; border: 1px solid #555; }"
                " QPushButton:hover { background: #4a4a4a; }"
            )
            selected_style = (
                "QPushButton { border-radius: 12px; padding: 4px 10px;"
                " font-family: monospace; font-size: 11px;"
                " background: #2196F3; color: #fff; border: 1px solid #2196F3; }"
            )
            boxes = self._plate_overlay._current_boxes()
            sel = self._plate_overlay._selected_idx
            for i, box in enumerate(boxes):
                kind = "M" if box.manual else "D"
                text = (
                    f"[{kind}] ({box.x:.2f},{box.y:.2f}) "
                    f"{box.w:.2f}\u00d7{box.h:.2f} "
                    f"C:{box.confidence:.0%}"
                )
                chip = QPushButton(text)
                chip.setFocusPolicy(Qt.NoFocus)
                chip.setCursor(Qt.PointingHandCursor)
                chip.setStyleSheet(selected_style if i == sel else chip_style)
                chip.clicked.connect(lambda checked, idx=i: self._on_plate_chip_clicked(idx))
                self._plate_chips_layout.addWidget(chip)
            self._plate_chips_layout.addStretch()
        finally:
            self._plate_list_updating = False

    def _on_plate_chip_clicked(self, idx: int):
        """Handle user clicking a plate chip."""
        if self._plate_list_updating:
            return
        self._plate_overlay.select_box(idx)
        self._refresh_plate_list()
        self._restore_keyboard_focus()

    def _restore_keyboard_focus(self):
        # Ensures page-scoped shortcuts keep working after chip interactions.
        top = self.window()
        if top is not None:
            top.activateWindow()
        self.setFocus()

    def _update_plate_overlay_frame(self, position: float):
        """Update the overlay's current frame based on video playback position."""
        if not self._plate_overlay.isVisible():
            self._update_frame_buttons()
            return
        frame_num = self._player.frame_at(position)
        self._plate_overlay.set_current_frame(frame_num)
        self._position_overlay()
        self._schedule_plate_list_refresh()
        self._update_frame_buttons()
        if self._btn_preview_blur.isChecked():
            self._schedule_blur_preview()

    def _on_add_plate(self, cursor_nx: float | None = None, cursor_ny: float | None = None):
        """Add a manual plate box at the current frame.

        *cursor_nx/ny* are normalized coordinates from a right-click.  When
        called from the button the overlay's last mouse position is used instead.
        """
        if not self._plate_overlay.isVisible():
            return

        # Get current clip data
        selected = self._timeline.selected_index
        if selected < 0 or selected not in self._plate_data:
            # Create clip data if detection was run but this clip has no data yet
            if selected >= 0:
                self._plate_data[selected] = ClipPlateData(clip_index=selected)
                self._plate_overlay.set_clip_data(self._plate_data[selected])

        # Clone from nearest detection (prior preferred, then next frame)
        ref = self._plate_overlay.find_nearest_reference_box()
        if ref:
            new_box = PlateBox(
                x=ref.x, y=ref.y, w=ref.w, h=ref.h,
                confidence=0.0, manual=True,
            )
        else:
            # Resolve cursor position for fallback placement
            if cursor_nx is None or cursor_ny is None:
                mouse_pos = self._plate_overlay.get_last_mouse_norm_pos()
                if mouse_pos is not None:
                    cursor_nx, cursor_ny = mouse_pos

            default_w, default_h = 0.15, 0.05
            if cursor_nx is not None and cursor_ny is not None:
                # Center the box on the cursor, clamped to frame
                bx = max(0.0, min(1.0 - default_w, cursor_nx - default_w / 2))
                by = max(0.0, min(1.0 - default_h, cursor_ny - default_h / 2))
            else:
                bx, by = 0.425, 0.475

            new_box = PlateBox(
                x=bx, y=by, w=default_w, h=default_h,
                confidence=0.0, manual=True,
            )

        self._plate_overlay.add_box(new_box)

    def _on_plate_selection_changed(self):
        """Sync overlay selection state to the plate list widget."""
        self._refresh_plate_list()

    def _on_plate_box_changed(self):
        """Handle box modification (add/move/resize/delete) — refresh list and save."""
        self._refresh_plate_list()
        self._save_plates()
        if self._btn_preview_blur.isChecked():
            self._update_blur_preview()

    # --- Blur Preview ---

    def _on_toggle_blur_preview(self, checked: bool):
        """Toggle blur preview on/off."""
        self._btn_preview_blur.setText("Blur ON" if checked else "Preview Blur")
        if checked:
            self._update_blur_preview()
        else:
            self._plate_overlay.clear_blur_tiles()
            if self._blur_preview_timer is not None:
                self._blur_preview_timer.stop()

    def _schedule_blur_preview(self):
        """Throttle blur preview updates to at most once every 100ms."""
        if self._blur_preview_timer is None:
            self._blur_preview_timer = QTimer(self)
            self._blur_preview_timer.setSingleShot(True)
            self._blur_preview_timer.setInterval(100)
            self._blur_preview_timer.timeout.connect(self._update_blur_preview)
        # Restart the timer — if already running, the old timeout is cancelled
        self._blur_preview_timer.start()

    def _update_blur_preview(self):
        """Grab current frame, blur plate regions, update overlay tiles."""
        if not self._btn_preview_blur.isChecked():
            return
        if not self._video_path:
            return

        selected = self._timeline.selected_index
        if selected < 0 or selected not in self._plate_data:
            self._plate_overlay.clear_blur_tiles()
            return

        clip_data = self._plate_data[selected]
        frame_num = self._plate_overlay._current_frame
        boxes = clip_data.detections.get(frame_num, [])
        if not boxes:
            self._plate_overlay.clear_blur_tiles()
            return

        # Grab the frame from QMediaPlayer — matches what the user sees
        # and what the detection (OpenCV sequential reading) produces.
        from trailvideocut.plate.blur import apply_blur_to_frame

        frame = self._player.grab_current_frame()
        if frame is None:
            self._plate_overlay.clear_blur_tiles()
            return

        fh, fw = frame.shape[:2]
        # Apply blur to get the blurred frame
        apply_blur_to_frame(frame, boxes, fh, fw)

        # Extract blurred regions as QPixmap tiles
        from PySide6.QtGui import QImage, QPixmap

        tiles = []
        for box in boxes:
            x1 = max(0, int(box.x * fw))
            y1 = max(0, int(box.y * fh))
            x2 = min(fw, int((box.x + box.w) * fw))
            y2 = min(fh, int((box.y + box.h) * fh))
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue

            region = frame[y1:y2, x1:x2].copy()
            # Convert BGR to RGB for QImage
            region_rgb = region[:, :, ::-1].copy()
            h, w = region_rgb.shape[:2]
            qimg = QImage(region_rgb.data, w, h, w * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            tiles.append(((box.x, box.y, box.w, box.h), pixmap))

        self._plate_overlay.set_blur_tiles(tiles)

    def _save_plates(self):
        """Persist plate data to the sidecar file."""
        if self._video_path and self._plate_data:
            save_plates(self._video_path, self._plate_data)
            self._btn_clear_plates.setEnabled(True)
            self._lbl_plate_status.setText("")

    def _on_clear_plates(self):
        """Delete sidecar file and clear all in-memory plate data."""
        if self._video_path:
            delete_plates(self._video_path)
        self._plate_data = {}
        self._plate_overlay.set_clip_data(None)
        self._plate_overlay.setVisible(False)
        self._chk_show_plates.setEnabled(False)
        self._btn_add_plate.setEnabled(False)
        self._btn_clear_plates.setEnabled(False)
        self._btn_detect_frame.setEnabled(False)
        self._btn_clear_clip_plates.setEnabled(False)
        self._btn_clear_frame_plates.setEnabled(False)
        self._lbl_plate_status.setText("")
        self._refresh_plate_list()

    # --- Single-frame detection ---

    def _get_detector_settings(self) -> tuple:
        """Return a tuple fingerprint of current UI detection settings."""
        return (
            self._spin_confidence.value(),
            self._chk_exclude_phones.isChecked(),
            self._spin_phone_gap.value(),
            self._spin_min_ratio.value(),
            self._spin_max_ratio.value(),
            self._spin_min_w.value(),
            self._spin_min_h.value(),
        )

    def _get_or_create_detector(self, model_path: str):
        """Return a cached PlateDetector, recreating if settings changed."""
        from trailvideocut.plate.detector import PlateDetector

        settings = self._get_detector_settings()
        if self._cached_detector is not None and self._cached_detector_settings == settings:
            return self._cached_detector

        self._cached_detector = PlateDetector(
            model_path=model_path,
            confidence_threshold=self._spin_confidence.value(),
            exclude_phones=self._chk_exclude_phones.isChecked(),
            phone_redetect_every=self._spin_phone_gap.value(),
            verbose=self._chk_debug_plates.isChecked(),
            min_ratio=self._spin_min_ratio.value(),
            max_ratio=self._spin_max_ratio.value(),
            min_plate_px_w=self._spin_min_w.value(),
            min_plate_px_h=self._spin_min_h.value(),
        )
        self._cached_detector_settings = settings
        return self._cached_detector

    def _on_detect_frame(self):
        """Run plate detection on the current frame only."""
        from trailvideocut.plate.model_manager import get_model_path

        clips = self._timeline.clips
        if not clips or not self._video_path:
            return

        model_path = get_model_path()
        if model_path is not None:
            self._run_single_frame_detection(str(model_path))
            return

        # Model not cached — download it, then run frame detection
        self._pending_frame_detect = True
        self._start_model_download()

    def _run_single_frame_detection(self, model_path: str):
        """Extract current frame and run tiled detection on it."""
        import cv2 as _cv2

        selected = self._timeline.selected_index
        clips = self._timeline.clips
        if selected < 0 or selected >= len(clips):
            # Try to find clip at current position
            current_time = self._player.current_time
            for i, clip in enumerate(clips):
                if clip.source_start <= current_time <= clip.source_end:
                    selected = i
                    break
            if selected < 0:
                return

        frame_num = self._player.frame_at(self._player.current_time)

        # Extract frame from video
        cap = _cv2.VideoCapture(self._video_path)
        cap.set(_cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            QMessageBox.warning(
                self, "Frame Read Error",
                f"Could not read frame {frame_num} from the video.",
            )
            return

        detector = self._get_or_create_detector(model_path)
        new_boxes = detector.detect_frame_tiled(frame)

        if self._chk_debug_plates.isChecked():
            print(f"[PlateDetect] Frame {frame_num}: {len(new_boxes)} boxes detected")

        # Get or create clip data
        if selected not in self._plate_data:
            self._plate_data[selected] = ClipPlateData(clip_index=selected)

        clip_data = self._plate_data[selected]

        # Preserve manual boxes for this frame
        existing_boxes = clip_data.detections.get(frame_num, [])
        manual_boxes = [b for b in existing_boxes if b.manual]

        # Replace auto boxes with new detections, keep manuals
        if new_boxes or manual_boxes:
            clip_data.detections[frame_num] = new_boxes + manual_boxes
        elif frame_num in clip_data.detections:
            del clip_data.detections[frame_num]

        self._save_plates()

        # Enable plate UI and refresh
        self._chk_show_plates.setEnabled(True)
        self._btn_add_plate.setEnabled(True)
        self._btn_clear_plates.setEnabled(True)
        self._plate_overlay.setVisible(self._chk_show_plates.isChecked())
        self._sync_overlay_to_current_clip()
        self._update_frame_buttons()

    # --- Clear clip / frame plates ---

    def _on_clear_clip_plates(self):
        """Delete all plates for the selected clip after confirmation."""
        selected = self._timeline.selected_index
        if selected < 0 or selected not in self._plate_data:
            return

        reply = QMessageBox.question(
            self, "Clear Clip Plates",
            f"Delete all plates (detected and manual) for clip {selected + 1}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        del self._plate_data[selected]

        if not self._plate_data:
            # No plate data left — clean up fully
            if self._video_path:
                delete_plates(self._video_path)
            self._plate_overlay.set_clip_data(None)
            self._plate_overlay.setVisible(False)
            self._chk_show_plates.setEnabled(False)
            self._btn_add_plate.setEnabled(False)
            self._btn_clear_plates.setEnabled(False)
            self._btn_detect_frame.setEnabled(False)
            self._btn_clear_clip_plates.setEnabled(False)
            self._btn_clear_frame_plates.setEnabled(False)
        else:
            self._save_plates()
            self._sync_overlay_to_current_clip()

        self._refresh_plate_list()
        self._update_frame_buttons()

    def _on_delete_key(self):
        """Del/Backspace: delete selected plate, or clear frame if none selected."""
        if self._plate_overlay.selected_box() is not None:
            self._plate_overlay.delete_selected()
        else:
            self._on_clear_frame_plates()

    def _on_clear_frame_plates(self):
        """Delete all plates for the current frame."""
        selected = self._timeline.selected_index
        if selected < 0 or selected not in self._plate_data:
            return

        frame_num = self._player.frame_at(self._player.current_time)
        clip_data = self._plate_data[selected]

        if frame_num not in clip_data.detections:
            return

        del clip_data.detections[frame_num]
        self._save_plates()
        self._sync_overlay_to_current_clip()
        self._update_frame_buttons()

    # --- Button state helpers ---

    def _update_frame_buttons(self):
        """Update enabled state of Detect Frame, Clear Clip Plates, Clear Frame Plates."""
        selected = self._timeline.selected_index
        clips = self._timeline.clips
        has_video = bool(self._video_path)
        has_clip = 0 <= selected < len(clips) if clips else False
        detecting = self._plate_worker is not None

        # Detect Frame: needs video + clip selected + not currently detecting
        self._btn_detect_frame.setEnabled(has_video and has_clip and not detecting)

        # Clear Clip Plates: needs selected clip with plate data
        clip_has_plates = has_clip and selected in self._plate_data
        self._btn_clear_clip_plates.setEnabled(clip_has_plates and not detecting)

        # Clear Frame Plates: needs current frame with plates
        frame_has_plates = False
        if clip_has_plates:
            frame_num = self._player.frame_at(self._player.current_time)
            frame_has_plates = frame_num in self._plate_data[selected].detections
        self._btn_clear_frame_plates.setEnabled(frame_has_plates and not detecting)

        # Preview Blur: needs clip with plate data
        self._btn_preview_blur.setEnabled(clip_has_plates and not detecting)

