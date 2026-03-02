from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

from rich.console import Console

from smartcut.audio.analyzer import AudioAnalyzer
from smartcut.audio.models import AudioAnalysis
from smartcut.audio.structure import MusicalStructureAnalyzer
from smartcut.config import SmartCutConfig
from smartcut.editor.assembler import VideoAssembler
from smartcut.editor.selector import SegmentSelector
from smartcut.video.analyzer import VideoAnalyzer
from smartcut.video.models import VideoSegment

console = Console()


class SmartCutPipeline:
    """Orchestrator: analyze audio/video, select segments, assemble output."""

    def __init__(self, config: SmartCutConfig):
        self.config = config

    def run(self) -> None:
        """Execute the full pipeline."""
        self._validate_inputs()

        # Run audio and video analysis concurrently — they are fully independent
        with ThreadPoolExecutor(max_workers=2) as executor:
            audio_future = executor.submit(self._run_audio_analysis)
            video_future = executor.submit(self._run_video_analysis)

            # Video analysis takes much longer; audio results arrive first
            audio_analysis = audio_future.result()
            segments, source_fps = video_future.result()

        # Print audio results (buffered until both phases done)
        console.print("\n[bold blue]Phase 1/4:[/] Audio analysis complete")
        console.print(
            f"  Tempo: {audio_analysis.tempo:.1f} BPM, "
            f"{len(audio_analysis.beats)} beats detected, "
            f"duration: {audio_analysis.duration:.1f}s"
        )
        for s in audio_analysis.sections:
            console.print(
                f"  [{s.label:8s}] {s.start_time:6.1f}s - {s.end_time:6.1f}s "
                f"(energy: {s.energy:.2f})"
            )

        # Print video results
        console.print(f"\n[bold blue]Phase 2/4:[/] Video analysis complete")
        console.print(f"  {len(segments)} segments scored")

        # Resolve auto-detect FPS from source video
        if self.config.output_fps == 0:
            self.config.output_fps = source_fps
            frac = Fraction(self.config.output_fps).limit_denominator(100000)
            console.print(f"  Using source video FPS: {frac.numerator}/{frac.denominator} ({self.config.output_fps:.6f})")

        # Show top 5 most interesting segments
        top_segments = sorted(segments, key=lambda s: s.interest.composite, reverse=True)[:5]
        for seg in top_segments:
            console.print(
                f"  [green]Top:[/] {seg.start_time:.1f}s-{seg.end_time:.1f}s "
                f"(score: {seg.interest.composite:.3f})"
            )

        # Phase 3: Segment selection
        console.print("\n[bold blue]Phase 3/4:[/] Selecting best segments...")
        selector = SegmentSelector(self.config)
        cut_plan = selector.select(audio_analysis, segments)
        console.print(
            f"  {cut_plan.zones_analyzed} zones analyzed, "
            f"merged to {len(cut_plan.decisions)} continuous clips, "
            f"total duration: {cut_plan.total_duration:.1f}s"
        )

        # Phase 4: Assembly
        console.print("\n[bold blue]Phase 4/4:[/] Assembling final video...")
        assembler = VideoAssembler(self.config)
        assembler.assemble(cut_plan)
        console.print(f"\n[bold green]Done![/] Output saved to: {self.config.output_path}")

    def _run_audio_analysis(self) -> AudioAnalysis:
        """Phase 1 + 1b: Analyze audio beats and musical structure."""
        audio_analyzer = AudioAnalyzer(self.config)
        audio_analysis = audio_analyzer.analyze()

        structure_analyzer = MusicalStructureAnalyzer()
        audio_analysis.sections = structure_analyzer.analyze(
            str(self.config.audio_path), y=audio_analysis.raw_audio
        )

        return audio_analysis

    def _run_video_analysis(self) -> tuple[list[VideoSegment], float]:
        """Phase 2: Analyze video for visual interest."""
        video_analyzer = VideoAnalyzer(self.config)
        segments = video_analyzer.analyze()
        return segments, video_analyzer.source_fps

    def _validate_inputs(self) -> None:
        """Validate input files exist and have supported formats."""
        if not self.config.video_path.exists():
            raise FileNotFoundError(f"Video not found: {self.config.video_path}")
        if not self.config.audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {self.config.audio_path}")

        video_exts = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
        audio_exts = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

        if self.config.video_path.suffix.lower() not in video_exts:
            raise ValueError(f"Unsupported video format: {self.config.video_path.suffix}")
        if self.config.audio_path.suffix.lower() not in audio_exts:
            raise ValueError(f"Unsupported audio format: {self.config.audio_path.suffix}")

        # Validate include timestamps
        for ts in self.config.include_timestamps:
            if ts < 0:
                raise ValueError(f"Include timestamp must be non-negative: {ts}")
