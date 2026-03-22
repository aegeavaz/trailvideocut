import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

from rich.console import Console

from trailvideocut.audio.analyzer import AudioAnalyzer
from trailvideocut.audio.energy_curve import (
    compute_smoothed_energy,
    detect_energy_transitions,
)
from trailvideocut.audio.models import AudioAnalysis
from trailvideocut.audio.structure import MusicalStructureAnalyzer
from trailvideocut.config import TrailVideoCutConfig
from trailvideocut.editor.assembler import VideoAssembler
from trailvideocut.editor.cut_points import energy_to_density, select_cut_points
from trailvideocut.editor.selector import SegmentSelector
from trailvideocut.gpu import detect_gpu
from trailvideocut.video.analyzer import VideoAnalyzer
from trailvideocut.video.models import VideoSegment

console = Console()


class TrailVideoCutPipeline:
    """Orchestrator: analyze audio/video, select segments, assemble output."""

    def __init__(self, config: TrailVideoCutConfig):
        self.config = config

    def run(self) -> None:
        """Execute the full pipeline."""
        self._validate_inputs()

        # Log GPU capabilities
        if self.config.use_gpu:
            caps = detect_gpu()
            if caps.any_gpu:
                mode_parts = []
                if caps.cupy_available:
                    mode_parts.append("CuPy scoring")
                if caps.hwaccel_available:
                    mode_parts.append(f"HW decode ({', '.join(caps.hwaccels)})")
                elif caps.nvdec_available:
                    mode_parts.append("NVDEC decoding")
                if caps.nvenc_available:
                    mode_parts.append("NVENC encoding")
                console.print(f"  GPU acceleration: {', '.join(mode_parts)}")
            else:
                console.print("  [yellow]GPU requested but not available — using CPU[/]")
        else:
            console.print("  GPU acceleration: disabled")

        # Run audio and video analysis concurrently — they are fully independent
        with ThreadPoolExecutor(max_workers=2) as executor:
            audio_future = executor.submit(self._run_audio_analysis)
            video_future = executor.submit(self._run_video_analysis)

            # Video analysis takes much longer; audio results arrive first
            audio_analysis = audio_future.result()
            segments, source_fps = video_future.result()

        # Print audio results (buffered until both phases done)
        console.print("\n[bold blue]Phase 1/5:[/] Audio analysis complete")
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
        console.print(f"\n[bold blue]Phase 2/5:[/] Video analysis complete")
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

        # Detect energy transitions for intra-section cut forcing
        energy_curve, energy_times = compute_smoothed_energy(
            audio_analysis.onset_envelope,
            audio_analysis.sample_rate,
            smooth_window_sec=self.config.energy_smooth_window,
        )
        energy_transitions = detect_energy_transitions(
            energy_curve,
            energy_times,
            min_magnitude=self.config.energy_transition_threshold,
        )
        if energy_transitions:
            console.print(f"\n  Detected {len(energy_transitions)} energy transition(s):")
            for t in energy_transitions:
                console.print(
                    f"    {t.timestamp:6.1f}s ({t.direction}, magnitude: {t.magnitude:.2f})"
                )

        # Phase 3: Energy-driven cut point selection
        console.print("\n[bold blue]Phase 3/5:[/] Selecting cut points by energy...")
        cut_points = select_cut_points(
            audio_analysis.beats,
            audio_analysis.sections,
            audio_analysis.tempo,
            self.config.min_segment_duration,
            self.config.max_segment_duration,
            energy_transitions=energy_transitions,
        )
        console.print(
            f"  {len(audio_analysis.beats)} beats -> {len(cut_points)} cut points"
        )
        for s in audio_analysis.sections:
            section_cuts = sum(
                1 for cp in cut_points
                if s.start_time <= cp.timestamp < s.end_time
            )
            density = energy_to_density(
                s.energy, audio_analysis.tempo,
                self.config.min_segment_duration, self.config.max_segment_duration,
            )
            interval = 1.0 / density if density > 0 else float('inf')
            effective_interval = max(interval, self.config.min_segment_duration)
            console.print(
                f"  [{s.label:8s}] energy={s.energy:.2f}, "
                f"interval={effective_interval:.1f}s, {section_cuts} cuts"
            )

        # Phase 4: Segment selection
        console.print("\n[bold blue]Phase 4/5:[/] Selecting best segments...")
        selector = SegmentSelector(self.config)
        cut_plan = selector.select(
            audio_analysis, segments,
            cut_points=cut_points,
            energy_transitions=energy_transitions,
        )
        n_intervals = len(cut_points) - 1
        console.print(
            f"  {n_intervals} beat intervals, "
            f"{cut_plan.clips_selected} clips selected (CV: {cut_plan.score_cv:.3f}), "
            f"merged to {len(cut_plan.decisions)} continuous clips"
        )
        if cut_plan.clips_selected < n_intervals:
            console.print(
                f"  [yellow]Quality-adaptive: reduced from {n_intervals} to "
                f"{cut_plan.clips_selected} clips (uniform footage)[/]"
            )
        for i, d in enumerate(cut_plan.decisions):
            duration = d.source_end - d.source_start
            console.print(
                f"  Clip {i+1:3d}: {d.source_start:6.1f}s - {d.source_end:6.1f}s "
                f"(dur: {duration:.1f}s, score: {d.interest_score:.3f})"
            )

        # Per-section clip duration summary
        for s in audio_analysis.sections:
            section_clips = [
                d for d in cut_plan.decisions
                if d.target_start >= s.start_time and d.target_start < s.end_time
            ]
            if section_clips:
                durs = [d.target_end - d.target_start for d in section_clips]
                avg_dur = sum(durs) / len(durs)
                console.print(
                    f"  [{s.label:8s}] {len(section_clips)} clips, "
                    f"avg duration: {avg_dur:.1f}s (energy: {s.energy:.2f})"
                )

        # Phase 5: Assembly or clip export
        if self.config.davinci:
            from trailvideocut.editor.exporter import DaVinciExporter

            # Auto-resolve output path for CLI: .mp4 default → .otio
            if self.config.output_path.suffix.lower() == ".mp4":
                self.config.output_path = self.config.video_path.parent / "project.otio"

            console.print("\n[bold blue]Phase 5/5:[/] Exporting OTIO timeline...")
            exporter = DaVinciExporter(self.config)
            t0 = time.time()
            otio_path = exporter.export(cut_plan)
            export_elapsed = time.time() - t0
            console.print(f"\n[bold green]Done![/] OTIO exported to: {otio_path}")
            console.print(f"  Export time: {export_elapsed:.1f}s")
        else:
            console.print("\n[bold blue]Phase 5/5:[/] Assembling final video...")
            assembler = VideoAssembler(self.config)
            t0 = time.time()
            assembler.assemble(cut_plan)
            assembly_elapsed = time.time() - t0
            console.print(f"\n[bold green]Done![/] Output saved to: {self.config.output_path}")
            minutes, secs = divmod(assembly_elapsed, 60)
            if minutes >= 1:
                console.print(f"  Assembly time: {int(minutes)}m {secs:.1f}s")
            else:
                console.print(f"  Assembly time: {secs:.1f}s")

    def _run_audio_analysis(self) -> AudioAnalysis:
        """Phase 1 + 1b: Analyze audio beats and musical structure."""
        audio_analyzer = AudioAnalyzer(self.config)
        audio_analysis = audio_analyzer.analyze()

        structure_analyzer = MusicalStructureAnalyzer()
        audio_analysis.sections = structure_analyzer.analyze(
            str(self.config.audio_path),
            y=audio_analysis.raw_audio,
            onset_envelope=audio_analysis.onset_envelope,
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
