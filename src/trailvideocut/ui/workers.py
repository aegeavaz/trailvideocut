from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from trailvideocut.audio.analyzer import AudioAnalyzer
from trailvideocut.audio.energy_curve import (
    compute_smoothed_energy,
    detect_energy_transitions,
)
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

            # Detect energy transitions
            energy_curve, energy_times = compute_smoothed_energy(
                audio_analysis.onset_envelope,
                audio_analysis.sample_rate,
                smooth_window_sec=self._config.energy_smooth_window,
            )
            energy_transitions = detect_energy_transitions(
                energy_curve,
                energy_times,
                min_magnitude=self._config.energy_transition_threshold,
            )

            # Phase 3: cut point selection
            self.status.emit("Selecting cut points...")
            cut_points = select_cut_points(
                audio_analysis.beats,
                audio_analysis.sections,
                audio_analysis.tempo,
                self._config.min_segment_duration,
                self._config.max_segment_duration,
                energy_transitions=energy_transitions,
            )

            # Phase 4: segment selection
            self.status.emit("Selecting best segments...")
            selector = SegmentSelector(self._config)
            cut_plan = selector.select(
                audio_analysis, segments,
                cut_points=cut_points,
                energy_transitions=energy_transitions,
            )

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

    def __init__(self, config: TrailVideoCutConfig, cut_plan: CutPlan, plate_data=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._cut_plan = cut_plan
        self._plate_data = plate_data

    def run(self):
        try:
            if self._config.davinci:
                from trailvideocut.editor.exporter import DaVinciExporter

                self.status.emit("Exporting OTIO timeline...")
                exporter = DaVinciExporter(self._config)
                path = exporter.export(self._cut_plan, plate_data=self._plate_data)
                self.finished.emit(str(path))
            else:
                self.status.emit("Assembling video with FFmpeg...")

                def _progress_cb(current: int, total: int) -> None:
                    self.progress.emit(current, total)

                def _status_cb(message: str) -> None:
                    self.status.emit(message)

                assembler = VideoAssembler(
                    self._config,
                    progress_callback=_progress_cb,
                    status_callback=_status_cb,
                )
                assembler.assemble(self._cut_plan, plate_data=self._plate_data)
                self.finished.emit(str(self._config.output_path))
        except Exception as e:
            self.error.emit(str(e))


class PlateDetectionWorker(QThread):
    """Runs plate detection on one or more clips in a background thread."""

    progress = Signal(int, int, int)  # clip_index, frame, total_frames
    finished = Signal(object)  # {clip_index: ClipPlateData}
    error = Signal(str)

    def __init__(
        self,
        video_path: str | Path,
        clips: list[tuple[int, float, float]],  # [(clip_index, start, end), ...]
        model_path: str | Path,
        confidence_threshold: float = 0.25,
        tiled: bool = True,
        exclude_phones: bool = False,
        phone_redetect_every: int = 30,
        debug: bool = False,
        min_ratio: float = 1.2,
        max_ratio: float = 2.0,
        min_plate_px_w: int = 15,
        min_plate_px_h: int = 10,
        min_track_length: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self._video_path = str(video_path)
        self._clips = clips
        self._model_path = str(model_path)
        self._threshold = confidence_threshold
        self._tiled = tiled
        self._exclude_phones = exclude_phones
        self._phone_redetect_every = phone_redetect_every
        self._debug = debug
        self._min_ratio = min_ratio
        self._max_ratio = max_ratio
        self._min_plate_px_w = min_plate_px_w
        self._min_plate_px_h = min_plate_px_h
        self._min_track_length = min_track_length
        self._cancelled = False

    def stop(self):
        self._cancelled = True

    def run(self):
        try:
            from trailvideocut.plate.detector import PlateDetector

            detector = PlateDetector(
                self._model_path, self._threshold,
                exclude_phones=self._exclude_phones,
                phone_redetect_every=self._phone_redetect_every,
                verbose=self._debug,
                min_ratio=self._min_ratio,
                max_ratio=self._max_ratio,
                min_plate_px_w=self._min_plate_px_w,
                min_plate_px_h=self._min_plate_px_h,
            )
            results: dict = {}

            for clip_index, start, end in self._clips:
                if self._cancelled:
                    break

                def _progress(frames_done: int, total: int) -> None:
                    self.progress.emit(clip_index, frames_done, total)

                data = detector.detect_clip(
                    self._video_path, start, end,
                    clip_index=clip_index,
                    progress_callback=_progress,
                    cancelled=lambda: self._cancelled,
                    tiled=self._tiled,
                    min_track_length=self._min_track_length,
                )
                # `data` is a ClipPlateData; it carries `phone_zones` populated
                # by the detector when `exclude_phones=True`. No separate
                # signal is needed — zones ride along on the same object.
                results[clip_index] = data

            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class ModelDownloadWorker(QThread):
    """Downloads the plate detection ONNX model with progress reporting."""

    progress = Signal(int, int)  # bytes_downloaded, total_bytes
    finished = Signal(str)  # path to downloaded model
    error = Signal(str)

    def run(self):
        try:
            from trailvideocut.plate.model_manager import download_model

            path = download_model(
                progress_callback=lambda d, t: self.progress.emit(d, t),
            )
            self.finished.emit(str(path))
        except Exception as e:
            self.error.emit(str(e))
