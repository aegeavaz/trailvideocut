from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from smartcut.config import SmartCutConfig, TransitionStyle
from smartcut.gpu import detect_gpu
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
        TransitionStyle.CROSSFADE, "-t", "--transition", help="Transition style between cuts"
    ),
    include: Optional[list[float]] = typer.Option(
        None, "-i", "--include", help="Must-include video timestamps in seconds (repeatable)"
    ),
    analysis_fps: float = typer.Option(
        3.0, "--analysis-fps", help="FPS for video analysis sampling"
    ),
    segment_hop: float = typer.Option(
        0.5, "--segment-hop", help="Hop between overlapping analysis windows in seconds"
    ),
    crossfade_duration: float = typer.Option(
        0.2, "--crossfade", help="Crossfade duration in seconds"
    ),
    min_segment: float = typer.Option(
        1.0, "--min-segment", help="Minimum segment duration in seconds"
    ),
    max_segment: float = typer.Option(
        8.0, "--max-segment", help="Maximum segment duration in seconds"
    ),
    quality_cv: float = typer.Option(
        0.4, "--quality-cv", help="Score CV threshold below which clip count is reduced"
    ),
    quality_reduction: float = typer.Option(
        0.5, "--quality-reduction", help="Max fraction of intervals to remove when footage is uniform"
    ),
    output_fps: float = typer.Option(0, "--fps", help="Output video FPS (0 = match source video)"),
    preset: str = typer.Option(
        "veryslow", "--preset", help="ffmpeg encoding preset (ultrafast..veryslow)"
    ),
    threads: int = typer.Option(
        0, "--threads", help="FFmpeg encoding threads (0 = auto-detect)"
    ),
    gpu: bool = typer.Option(True, "--gpu/--no-gpu", help="Enable/disable GPU acceleration"),
    gpu_batch_size: int = typer.Option(
        64, "--gpu-batch-size", help="Frames per GPU batch for scoring"
    ),
    davinci: bool = typer.Option(
        False, "--davinci/--no-davinci", help="Export OTIO for DaVinci Resolve instead of rendering"
    ),
):
    """Cut a motorcycle POV video to sync with a song's beats."""
    config = SmartCutConfig(
        video_path=video,
        audio_path=audio,
        output_path=output,
        transition_style=transition,
        include_timestamps=include or [],
        analysis_fps=analysis_fps,
        segment_hop=segment_hop,
        crossfade_duration=crossfade_duration,
        min_segment_duration=min_segment,
        max_segment_duration=max_segment,
        quality_cv_threshold=quality_cv,
        quality_max_reduction=quality_reduction,
        output_fps=output_fps,
        output_preset=preset,
        output_threads=threads,
        use_gpu=gpu,
        gpu_batch_size=gpu_batch_size,
        davinci=davinci,
    )

    console.print("[bold]SmartCut[/] - Beat-synced video editor")
    console.print(f"  Video: {video}")
    console.print(f"  Audio: {audio}")
    if davinci:
        console.print("  Mode: DaVinci OTIO export")
    else:
        console.print(f"  Output: {output}")
    if include:
        console.print(f"  Must-include: {include}")

    # GPU status
    if gpu:
        caps = detect_gpu()
        if caps.gpu_name:
            console.print(f"  GPU: {caps.gpu_name} ({caps.gpu_memory_mb} MB)")
        hwdec_str = ", ".join(caps.hwaccels) if caps.hwaccels else "none"
        console.print(
            f"  CuPy: {'[green]yes[/]' if caps.cupy_available else '[yellow]no[/]'} | "
            f"HW decode: {'[green]' + hwdec_str + '[/]' if caps.hwaccel_available else '[yellow]none[/]'} | "
            f"NVENC: {'[green]yes[/]' if caps.nvenc_available else '[yellow]no[/]'}"
        )
        if not caps.any_gpu:
            console.print("  [yellow]No GPU features detected — falling back to CPU[/]")
    else:
        console.print("  GPU: [dim]disabled (--no-gpu)[/]")

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


@app.command(name="ui")
def launch_ui():
    """Launch the SmartCut graphical interface."""
    try:
        from smartcut.ui.app import launch
    except ImportError:
        console.print(
            "[bold red]Error:[/] PySide6 is required for the UI.\n"
            "Install it with: pip install 'smartcut[ui]'"
        )
        raise typer.Exit(code=1)
    launch()
