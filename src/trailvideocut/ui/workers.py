from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QThread, Signal

from trailvideocut.audio.analyzer import AudioAnalyzer
from trailvideocut.audio.models import AudioAnalysis
from trailvideocut.audio.structure import MusicalStructureAnalyzer
from trailvideocut.config import TrailVideoCutConfig
from trailvideocut.editor.assembler import VideoAssembler
from trailvideocut.editor.cut_points import select_cut_points
from trailvideocut.editor.models import CutPlan
from trailvideocut.editor.selector import SegmentSelector
from trailvideocut.video.analyzer import VideoAnalyzer
from trailvideocut.video.models import VideoSegment


class AnalysisWorker(QThread):
    """Runs audio/video analysis and segment selection in a background thread."""

    status = Signal(str)
    progress = Signal(int, int)  # current, total
    audio_done = Signal(object)  # AudioAnalysis
    video_done = Signal(object, float)  # list[VideoSegment], source_fps
    finished = Signal(object, object, object, float)  # AudioAnalysis, segments, CutPlan, fps
    error = Signal(str)

    def __init__(self, config: TrailVideoCutConfig, parent=None):
        super().__init__(parent)
        self._config = config

    def run(self):
        try:
            # Validate
            from trailvideocut.pipeline import TrailVideoCutPipeline

            pipeline = TrailVideoCutPipeline(self._config)
            pipeline._validate_inputs()

            # Phase 1+2: concurrent audio + video analysis
            self.status.emit("Analyzing audio and video...")

            with ThreadPoolExecutor(max_workers=2) as ex:
                audio_future = ex.submit(self._analyze_audio)
                video_future = ex.submit(self._analyze_video)

                audio_analysis = audio_future.result()
                segments, source_fps = video_future.result()

            self.audio_done.emit(audio_analysis)
            self.video_done.emit(segments, source_fps)

            # Resolve FPS
            if self._config.output_fps == 0:
                self._config.output_fps = source_fps

            # Phase 3: cut point selection
            self.status.emit("Selecting cut points...")
            cut_points = select_cut_points(
                audio_analysis.beats,
                audio_analysis.sections,
                audio_analysis.tempo,
                self._config.min_segment_duration,
                self._config.max_segment_duration,
            )

            # Phase 4: segment selection
            self.status.emit("Selecting best segments...")
            selector = SegmentSelector(self._config)
            cut_plan = selector.select(audio_analysis, segments, cut_points=cut_points)

            self.status.emit("Analysis complete.")
            self.finished.emit(audio_analysis, segments, cut_plan, source_fps)

        except Exception as e:
            self.error.emit(str(e))

    def _analyze_audio(self) -> AudioAnalysis:
        analyzer = AudioAnalyzer(self._config)
        analysis = analyzer.analyze()
        structure = MusicalStructureAnalyzer()
        analysis.sections = structure.analyze(
            str(self._config.audio_path),
            y=analysis.raw_audio,
            onset_envelope=analysis.onset_envelope,
        )
        return analysis

    def _analyze_video(self) -> tuple[list[VideoSegment], float]:
        def _progress_cb(current: int, total: int) -> None:
            self.progress.emit(current, total)

        def _status_cb(message: str) -> None:
            self.status.emit(message)

        analyzer = VideoAnalyzer(
            self._config,
            progress_callback=_progress_cb,
            status_callback=_status_cb,
        )
        segments = analyzer.analyze()
        return segments, analyzer.source_fps


class RenderWorker(QThread):
    """Runs video assembly or OTIO export in a background thread."""

    status = Signal(str)
    progress = Signal(int, int)  # current, total
    finished = Signal(str)  # output path
    error = Signal(str)

    def __init__(self, config: TrailVideoCutConfig, cut_plan: CutPlan, parent=None):
        super().__init__(parent)
        self._config = config
        self._cut_plan = cut_plan

    def run(self):
        try:
            if self._config.davinci:
                from trailvideocut.editor.exporter import DaVinciExporter

                self.status.emit("Exporting OTIO timeline...")
                exporter = DaVinciExporter(self._config)
                path = exporter.export(self._cut_plan)
                self.finished.emit(str(path))
            else:
                self.status.emit("Assembling video with FFmpeg...")

                def _progress_cb(current: int, total: int) -> None:
                    self.progress.emit(current, total)

                assembler = VideoAssembler(self._config, progress_callback=_progress_cb)
                assembler.assemble(self._cut_plan)
                self.finished.emit(str(self._config.output_path))
        except Exception as e:
            self.error.emit(str(e))
