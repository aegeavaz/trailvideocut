from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from trailvideocut.config import TrailVideoCutConfig, TransitionStyle
from trailvideocut.gpu import detect_gpu
from trailvideocut.pipeline import TrailVideoCutPipeline

app = typer.Typer(
    name="trailvideocut",
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
    config = TrailVideoCutConfig(
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

    console.print("[bold]TrailVideoCut[/] - Beat-synced video editor")
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
        pipeline = TrailVideoCutPipeline(config)
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
        from trailvideocut.audio.analyzer import AudioAnalyzer
        from trailvideocut.audio.structure import MusicalStructureAnalyzer

        console.print(f"[bold]Analyzing audio:[/] {audio}")
        config = TrailVideoCutConfig(video_path=Path("dummy.mp4"), audio_path=audio)
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
        from trailvideocut.video.analyzer import VideoAnalyzer

        console.print(f"\n[bold]Analyzing video:[/] {video}")
        config = TrailVideoCutConfig(video_path=video, audio_path=Path("dummy.wav"))
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
    """Launch the TrailVideoCut graphical interface."""
    try:
        from trailvideocut.ui.app import launch
    except ImportError:
        console.print(
            "[bold red]Error:[/] PySide6 is required for the UI.\n"
            "Install it with: pip install 'trailvideocut[ui]'"
        )
        raise typer.Exit(code=1)
    launch()


@app.command(name="detect-plates")
def detect_plates(
    video: Path = typer.Argument(..., help="Path to the input video file", exists=True),
    output_dir: Path = typer.Option(
        Path("plate_debug"), "-o", "--output-dir", help="Output directory for debug artifacts"
    ),
    start: float = typer.Option(0.0, "--start", help="Start time in seconds"),
    end: float = typer.Option(0.0, "--end", help="End time in seconds (0 = end of video)"),
    threshold: float = typer.Option(0.1, "--threshold", help="Minimum detection confidence"),
    every_n: int = typer.Option(1, "--every-n", help="Process every Nth frame (1 = all frames)"),
    model: Optional[Path] = typer.Option(
        None, "--model", help="Custom ONNX model path (overrides default model)"
    ),
    tiled: bool = typer.Option(
        True, "--tiled/--no-tiled", help="Use tiled detection for small plates (default: tiled)"
    ),
    exclude_phones: bool = typer.Option(
        True, "--exclude-phones/--no-exclude-phones",
        help="Auto-detect phones/GPS devices and exclude from plate results",
    ),
    continuity_filter: bool = typer.Option(
        True, "--continuity-filter/--no-continuity-filter",
        help="Remove sporadic detections lacking temporal continuity",
    ),
):
    """Run plate detection on a video and save debug output (annotated frames + CSV log)."""
    import csv

    import cv2
    from rich.progress import Progress

    from trailvideocut.plate.model_manager import download_model, get_model_path

    console.print("[bold]Plate Detection Debug[/]")
    console.print(f"  Video: {video}")
    console.print(f"  Output: {output_dir}")
    console.print(f"  Threshold: {threshold}")
    if start > 0 or end > 0:
        console.print(f"  Range: {start}s - {'end' if end == 0 else f'{end}s'}")
    if every_n > 1:
        console.print(f"  Sampling: every {every_n} frames")
    console.print()

    # Resolve model: custom path > cached > download
    if model:
        model_path = model
        console.print(f"  Model: {model_path} (custom)")
    else:
        model_path = get_model_path()
    if model_path is None:
        console.print("[yellow]Downloading plate detection model...[/]")
        try:
            with Progress() as progress:
                task = progress.add_task("Downloading model...", total=None)

                def _dl_progress(downloaded: int, total: int) -> None:
                    if total > 0:
                        progress.update(task, total=total, completed=downloaded)

                model_path = download_model(progress_callback=_dl_progress)
            console.print(f"[green]Model downloaded:[/] {model_path}\n")
        except Exception as e:
            console.print(f"[bold red]Download failed:[/] {e}")
            raise typer.Exit(code=1)

    # Open video
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    start_frame = int(start * fps)
    end_frame = int(end * fps) if end > 0 else total_video_frames
    end_frame = min(end_frame, total_video_frames)

    console.print(f"  Video: {width}x{height} @ {fps:.1f} fps, {total_video_frames} frames")
    console.print(f"  Processing frames {start_frame} - {end_frame} "
                  f"(every {every_n})\n")

    # Clean and create output dir
    import shutil

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # Init detector
    from trailvideocut.plate.detector import PlateDetector

    detector = PlateDetector(
        str(model_path),
        confidence_threshold=threshold,
        exclude_phones=exclude_phones,
    )

    if detector._has_cuda:
        console.print(f"  [green]GPU: CUDA active ({detector.backend})[/]")
    else:
        console.print(f"  [yellow]GPU: not available — {detector.backend} (CPU)[/]")
    if exclude_phones:
        console.print("  [cyan]Phone exclusion: enabled[/]")
    console.print()

    # --- Pass 1: Detect and accumulate ---
    from trailvideocut.plate.models import ClipPlateData

    frames_to_process = list(range(start_frame, end_frame, every_n))
    clip_data = ClipPlateData(clip_index=0)

    with Progress() as progress:
        task = progress.add_task("Detecting plates...", total=len(frames_to_process))

        for frame_num in frames_to_process:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                break

            if tiled:
                boxes = detector.detect_frame_tiled(frame)
            else:
                boxes = detector.detect_frame(frame)

            if boxes:
                clip_data.detections[frame_num] = boxes

            progress.update(task, advance=1)

    cap.release()

    raw_count = sum(len(b) for b in clip_data.detections.values())

    # --- Temporal continuity filter ---
    if continuity_filter:
        from trailvideocut.plate.temporal_filter import filter_temporal_continuity

        clip_data = filter_temporal_continuity(
            clip_data,
            max_frame_gap=max(1, every_n),
        )
        filtered_count = sum(len(b) for b in clip_data.detections.values())
        console.print(
            f"  Temporal filter: {raw_count} -> {filtered_count} detections"
        )

    # --- Pass 2: Annotate frames and write CSV ---
    csv_path = output_dir / "detections.csv"
    csv_file = open(csv_path, "w", newline="")
    writer = csv.writer(csv_file)
    writer.writerow([
        "frame_number", "timestamp_s",
        "x", "y", "w", "h",
        "x_px", "y_px", "w_px", "h_px",
        "confidence",
    ])

    total_detections = 0
    frames_with_boxes = sorted(clip_data.detections.keys())

    if frames_with_boxes:
        cap = cv2.VideoCapture(str(video))

        with Progress() as progress:
            task = progress.add_task("Writing frames...", total=len(frames_with_boxes))

            for frame_num in frames_with_boxes:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    break

                for box in clip_data.detections[frame_num]:
                    x_px = int(box.x * width)
                    y_px = int(box.y * height)
                    w_px = int(box.w * width)
                    h_px = int(box.h * height)

                    cv2.rectangle(
                        frame,
                        (x_px, y_px),
                        (x_px + w_px, y_px + h_px),
                        (0, 200, 255),  # orange BGR
                        2,
                    )
                    label = f"{box.confidence:.0%}"
                    cv2.putText(
                        frame, label,
                        (x_px, y_px - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2,
                    )

                    timestamp = frame_num / fps
                    writer.writerow([
                        frame_num, f"{timestamp:.3f}",
                        f"{box.x:.6f}", f"{box.y:.6f}", f"{box.w:.6f}", f"{box.h:.6f}",
                        x_px, y_px, w_px, h_px,
                        f"{box.confidence:.6f}",
                    ])
                    total_detections += 1

                png_path = output_dir / f"frame_{frame_num:06d}.png"
                cv2.imwrite(str(png_path), frame)

                progress.update(task, advance=1)

        cap.release()

    csv_file.close()

    console.print(
        f"\n[bold green]Done![/] Processed {len(frames_to_process)} frames, "
        f"found {total_detections} plate detections."
    )
    console.print(f"  Frames: {output_dir}/frame_*.png")
    console.print(f"  Log:    {csv_path}")
