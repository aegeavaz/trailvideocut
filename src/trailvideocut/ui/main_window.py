from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from trailvideocut.audio.models import AudioAnalysis
from trailvideocut.config import TrailVideoCutConfig, TransitionStyle
from trailvideocut.editor.models import CutPlan
from trailvideocut.ui.export_page import ExportPage
from trailvideocut.ui.review_page import ReviewPage
from trailvideocut.ui.setup_page import SetupPage
from trailvideocut.ui.style import DARK_STYLESHEET
from trailvideocut.ui.workers import AnalysisWorker, RenderWorker
from trailvideocut.video.models import VideoSegment


class MainWindow(QMainWindow):
    """Main application window with wizard-style page navigation."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TrailVideoCut")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(DARK_STYLESHEET)

        # State
        self._config: TrailVideoCutConfig | None = None
        self._audio: AudioAnalysis | None = None
        self._segments: list[VideoSegment] = []
        self._cut_plan: CutPlan | None = None
        self._source_fps = 30.0
        self._video_duration = 0.0

        # Workers
        self._analysis_worker: AnalysisWorker | None = None
        self._render_worker: RenderWorker | None = None

        self._build_ui()
        self._connect_signals()

        # Start maximized
        self.showMaximized()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 4, 6, 0)
        layout.setSpacing(0)

        # Stacked pages
        self._pages = QStackedWidget()
        self._setup_page = SetupPage()
        self._review_page = ReviewPage()
        self._export_page = ExportPage()

        self._pages.addWidget(self._setup_page)   # 0
        self._pages.addWidget(self._review_page)   # 1
        self._pages.addWidget(self._export_page)   # 2

        layout.addWidget(self._pages, stretch=1)

        # Status bar
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Ready")

    def _connect_signals(self):
        self._setup_page.analyze_requested.connect(self._start_analysis)
        self._setup_page.go_to_review_requested.connect(self._go_to_review_directly)
        self._review_page.back_requested.connect(self._back_to_setup)
        self._review_page.export_requested.connect(self._go_to_export)
        self._export_page.back_requested.connect(lambda: self._go_page(1))
        self._export_page.start_export.connect(self._start_export)

    def _go_page(self, index: int):
        self._pages.setCurrentIndex(index)

    def _back_to_setup(self):
        self._go_page(0)
        if self._cut_plan is not None:
            self._setup_page.show_go_to_review(True)

    def _go_to_review_directly(self):
        if self._audio is None or self._cut_plan is None or self._config is None:
            return
        self._review_page.set_data(
            self._audio,
            self._cut_plan,
            self._video_duration,
            video_path=str(self._config.video_path),
            marks=list(self._config.include_timestamps),
            audio_path=str(self._config.audio_path),
        )
        self._go_page(1)

    # --- Analysis ---

    def _start_analysis(self, settings: dict):
        self._config = TrailVideoCutConfig(**settings)
        self._video_duration = self._setup_page.video_duration
        self._setup_page.show_go_to_review(False)

        self._statusbar.showMessage("Running analysis...")
        self._analysis_worker = AnalysisWorker(self._config, parent=self)
        self._analysis_worker.status.connect(self._on_analysis_status)
        self._analysis_worker.progress.connect(self._setup_page.set_progress)
        self._analysis_worker.finished.connect(self._on_analysis_done)
        self._analysis_worker.error.connect(self._on_analysis_error)
        self._analysis_worker.start()

    def _on_analysis_status(self, msg: str):
        self._statusbar.showMessage(msg)
        self._setup_page.set_progress_status(msg)

    def _on_analysis_done(
        self,
        audio: AudioAnalysis,
        segments: list[VideoSegment],
        cut_plan: CutPlan,
        source_fps: float,
    ):
        self._audio = audio
        self._segments = segments
        self._cut_plan = cut_plan
        self._source_fps = source_fps

        if segments:
            self._video_duration = segments[-1].end_time

        self._review_page.set_data(
            audio,
            cut_plan,
            self._video_duration,
            video_path=str(self._config.video_path),
            marks=list(self._config.include_timestamps),
            audio_path=str(self._config.audio_path),
        )

        if self._config:
            self._export_page.set_default_output(self._config.video_path)

        self._setup_page.set_analyze_enabled(True)
        self._setup_page.show_go_to_review(True)
        self._statusbar.showMessage(
            f"Analysis complete: {len(cut_plan.decisions)} clips, "
            f"{audio.tempo:.0f} BPM"
        )
        self._go_page(1)

    def _on_analysis_error(self, msg: str):
        self._setup_page.set_analyze_enabled(True)  # also resets progress bar
        self._statusbar.showMessage(f"Analysis error: {msg}")

    # --- Export navigation ---

    def _go_to_export(self):
        if self._config is None or self._cut_plan is None:
            return

        edited_clips = self._review_page.get_current_clips()
        self._cut_plan = CutPlan(
            decisions=edited_clips,
            total_duration=self._cut_plan.total_duration,
            song_tempo=self._cut_plan.song_tempo,
            transition_style=self._cut_plan.transition_style,
            crossfade_duration=self._cut_plan.crossfade_duration,
            clips_selected=self._cut_plan.clips_selected,
            score_cv=self._cut_plan.score_cv,
        )

        self._export_page.reset_status()
        self._go_page(2)

    # --- Rendering ---

    def _start_export(self, output_path: str, is_davinci: bool):
        if self._config is None or self._cut_plan is None:
            return

        # Read render settings from export page
        render_settings = self._export_page.get_render_settings()
        transition_str = render_settings.get("transition_style", "crossfade")
        self._config.transition_style = TransitionStyle(transition_str)
        self._config.crossfade_duration = render_settings.get("crossfade_duration", 0.2)
        self._config.output_preset = render_settings.get("output_preset", "veryslow")
        self._config.output_fps = render_settings.get("output_fps", 0)
        self._config.output_threads = render_settings.get("output_threads", 0)
        self._config.plate_blur_enabled = render_settings.get("plate_blur_enabled", True)
        self._config.plate_blur_strength = render_settings.get("plate_blur_strength", 1.0)

        # Rebuild cut plan with final transition settings
        self._cut_plan = CutPlan(
            decisions=self._cut_plan.decisions,
            total_duration=self._cut_plan.total_duration,
            song_tempo=self._cut_plan.song_tempo,
            transition_style=self._config.transition_style.value,
            crossfade_duration=self._config.crossfade_duration,
            clips_selected=self._cut_plan.clips_selected,
            score_cv=self._cut_plan.score_cv,
        )

        self._config.davinci = is_davinci
        self._config.output_path = Path(output_path)

        # Collect plate data for blur processing
        plate_data = self._review_page.plate_data if self._config.plate_blur_enabled else None

        self._statusbar.showMessage("Exporting...")
        self._render_worker = RenderWorker(
            self._config, self._cut_plan, plate_data=plate_data, parent=self,
        )
        self._render_worker.status.connect(self._on_render_status)
        self._render_worker.progress.connect(self._export_page.set_progress)
        self._render_worker.finished.connect(self._on_render_done)
        self._render_worker.error.connect(self._on_render_error)
        self._render_worker.start()

    def _on_render_status(self, msg: str):
        self._statusbar.showMessage(msg)
        self._export_page.set_status(msg)

    def _on_render_done(self, output_path: str):
        self._statusbar.showMessage(f"Export complete: {output_path}")
        self._export_page.set_finished(output_path)

    def _on_render_error(self, msg: str):
        self._statusbar.showMessage(f"Export error: {msg}")
        self._export_page.set_error(msg)
