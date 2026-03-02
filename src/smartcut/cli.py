from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from smartcut.config import SegmentPreference, SmartCutConfig, TransitionStyle
from smartcut.pipeline import SmartCutPipeline

app = typer.Typer(
    name="smartcut",
    help="Automatically cut motorcycle POV videos to sync with music beats.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def cut(
    video: Path = typer.Argument(..., help="Path to the input video file", exists=True),
    audio: Path = typer.Argument(..., help="Path to the input audio file (WAV/MP3)", exists=True),
    output: Path = typer.Option(
        Path("output.mp4"), "-o", "--output", help="Output video file path"
    ),
    transition: TransitionStyle = typer.Option(
        TransitionStyle.HARD_CUT, "-t", "--transition", help="Transition style between cuts"
    ),
    preference: SegmentPreference = typer.Option(
        SegmentPreference.BALANCED, "-p", "--preference", help="Segment selection preference"
    ),
    include: Optional[list[float]] = typer.Option(
        None, "-i", "--include", help="Must-include video timestamps in seconds (repeatable)"
    ),
    analysis_fps: float = typer.Option(
        3.0, "--analysis-fps", help="FPS for video analysis sampling"
    ),
    crossfade_duration: float = typer.Option(
        0.08, "--crossfade", help="Crossfade duration in seconds"
    ),
    min_segment: float = typer.Option(
        0.25, "--min-segment", help="Minimum segment duration in seconds"
    ),
    max_segment: float = typer.Option(
        8.0, "--max-segment", help="Maximum segment duration in seconds"
    ),
    output_fps: int = typer.Option(30, "--fps", help="Output video FPS"),
    preset: str = typer.Option(
        "medium", "--preset", help="ffmpeg encoding preset (ultrafast..veryslow)"
    ),
):
    """Cut a motorcycle POV video to sync with a song's beats."""
    config = SmartCutConfig(
        video_path=video,
        audio_path=audio,
        output_path=output,
        transition_style=transition,
        segment_preference=preference,
        include_timestamps=include or [],
        analysis_fps=analysis_fps,
        crossfade_duration=crossfade_duration,
        min_segment_duration=min_segment,
        max_segment_duration=max_segment,
        output_fps=output_fps,
        output_preset=preset,
    )

    console.print("[bold]SmartCut[/] - Beat-synced video editor")
    console.print(f"  Video: {video}")
    console.print(f"  Audio: {audio}")
    console.print(f"  Output: {output}")
    if include:
        console.print(f"  Must-include: {include}")
    console.print()

    try:
        pipeline = SmartCutPipeline(config)
        pipeline.run()
    except Exception as e:
        console.print(f"\n[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)


@app.command()
def analyze(
    video: Optional[Path] = typer.Option(None, "--video", "-v", help="Analyze video only"),
    audio: Optional[Path] = typer.Option(None, "--audio", "-a", help="Analyze audio only"),
):
    """Analyze video or audio independently (diagnostic mode)."""
    if not video and not audio:
        console.print("[red]Provide --video and/or --audio[/]")
        raise typer.Exit(code=1)

    if audio:
        from smartcut.audio.analyzer import AudioAnalyzer
        from smartcut.audio.structure import MusicalStructureAnalyzer

        console.print(f"[bold]Analyzing audio:[/] {audio}")
        config = SmartCutConfig(video_path=Path("dummy.mp4"), audio_path=audio)
        analyzer = AudioAnalyzer(config)
        result = analyzer.analyze()
        console.print(
            f"  Tempo: {result.tempo:.1f} BPM | "
            f"Beats: {len(result.beats)} | "
            f"Duration: {result.duration:.1f}s"
        )
        console.print("\n  Beat timestamps (first 20):")
        for beat in result.beats[:20]:
            marker = " [D]" if beat.is_downbeat else ""
            console.print(f"    {beat.timestamp:6.2f}s  strength={beat.strength:.2f}{marker}")

        console.print("\n  Musical structure:")
        sa = MusicalStructureAnalyzer()
        sections = sa.analyze(str(audio))
        for s in sections:
            console.print(
                f"    [{s.label:8s}] {s.start_time:6.1f}s - {s.end_time:6.1f}s "
                f"(energy: {s.energy:.2f})"
            )

    if video:
        from smartcut.video.analyzer import VideoAnalyzer

        console.print(f"\n[bold]Analyzing video:[/] {video}")
        config = SmartCutConfig(video_path=video, audio_path=Path("dummy.wav"))
        analyzer = VideoAnalyzer(config)
        segments = analyzer.analyze()
        console.print(f"  {len(segments)} segments analyzed\n")
        console.print("  Top 20 most interesting segments:")
        top = sorted(segments, key=lambda s: s.interest.composite, reverse=True)[:20]
        for seg in top:
            console.print(
                f"    [{seg.start_time:6.1f}s - {seg.end_time:6.1f}s] "
                f"score={seg.interest.composite:.3f} "
                f"(flow={seg.interest.optical_flow:.2f} "
                f"color={seg.interest.color_change:.2f} "
                f"edge={seg.interest.edge_variance:.2f} "
                f"bright={seg.interest.brightness_change:.2f})"
            )
