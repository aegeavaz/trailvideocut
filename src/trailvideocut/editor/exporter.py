from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import opentimelineio as otio
from rich.console import Console

from trailvideocut.config import TrailVideoCutConfig, TransitionStyle
from trailvideocut.editor.keyframes import probe_video_params
from trailvideocut.editor.models import CutPlan
from trailvideocut.plate.models import ClipPlateData

console = Console()
logger = logging.getLogger(__name__)


class DaVinciExporter:
    """Export an OTIO timeline referencing source video and audio directly."""

    def __init__(self, config: TrailVideoCutConfig):
        self.config = config

    def export(
        self,
        plan: CutPlan,
        plate_data: dict[int, ClipPlateData] | None = None,
    ) -> Path:
        video_path = self.config.video_path
        vparams = probe_video_params(str(video_path))

        r_frame_rate = vparams.get("r_frame_rate", "24000/1001")
        video_duration = vparams.get("duration", 0.0)
        timecode = vparams.get("timecode")
        fps = _parse_frame_rate(r_frame_rate)

        otio_path = self.config.output_path
        timeline = _generate_otio_timeline(
            plan, video_path, video_duration,
            self.config.audio_path, r_frame_rate, timecode,
            plate_data=plate_data if self.config.plate_blur_enabled else None,
            fps=fps,
        )
        timeline.to_json_file(str(otio_path))
        console.print(f"  OTIO: {otio_path}")
        transition_info = ""
        if plan.transition_style == TransitionStyle.CROSSFADE.value and len(plan.decisions) > 1:
            transition_info = f" with {plan.crossfade_duration}s crossfades"
        console.print(f"  {len(plan.decisions)} segments referenced from source video{transition_info}")

        # Generate companion files if plate data exists
        has_plates = plate_data and any(
            cpd.detections for cpd in plate_data.values()
        )
        if has_plates:
            from trailvideocut.editor.resolve_script import (
                generate_fusion_scripts,
                generate_resolve_script,
                try_execute_resolve_script,
            )

            # Always generate Fusion Lua scripts (works with Resolve Free)
            plate_clips = []
            for i, d in enumerate(plan.decisions):
                cpd = plate_data.get(i) if plate_data else None
                if not cpd or not cpd.detections:
                    continue
                # Use the same integer frame numbers OTIO writes for the
                # clip's source_range start (round, not int truncation), so
                # the Fusion clip-relative frame mapping aligns with how
                # Resolve positions the clip from the .otio file.
                # RationalTime.value is a float; cast to int for use as a
                # dict key / range bound.
                src_start_frame = int(_seconds_to_rational_time(d.source_start, fps).value)
                src_end_frame = int(_seconds_to_rational_time(d.source_end, fps).value)
                clip_dets = _build_clip_detections(cpd, src_start_frame, src_end_frame)
                if clip_dets:
                    frame_count = src_end_frame - src_start_frame
                    # Detect PTS gap from concatenated source videos.
                    # This is cached after the first call since the gap
                    # position is a property of the source file, not the clip.
                    pts_gap_kf = _detect_pts_gap_keyframe(
                        video_path, src_start_frame, src_end_frame,
                    )
                    plate_clips.append((
                        f"segment_{i + 1:03d}",
                        clip_dets,
                        fps,
                        frame_count,
                        src_start_frame,
                        pts_gap_kf,
                    ))

            if plate_clips:
                fusion_dir = otio_path.parent / (otio_path.stem + "_fusion")
                fusion_dir.mkdir(exist_ok=True)
                lua_paths = generate_fusion_scripts(plate_clips, fusion_dir)
                console.print(f"  Fusion scripts: {fusion_dir}/ ({len(lua_paths)} file(s))")
                console.print("  Usage: select clip > Fusion > Console > dofile('path/to/script.lua')")

            # Also generate automation script for Studio users
            script_content = generate_resolve_script(otio_path, fps)
            script_path = otio_path.with_name(
                otio_path.stem + "_resolve_plates.py",
            )
            script_path.write_text(script_content, encoding="utf-8")
            console.print(f"  Resolve script: {script_path}")

            if self.config.resolve_apply_blur:
                success, msg = try_execute_resolve_script(script_path)
                if success:
                    console.print("  [green]Blur applied in Resolve[/green]")
                else:
                    console.print(f"  [yellow]{msg}[/yellow]")

        return otio_path


def _path_to_file_url(path: Path) -> str:
    """Convert a filesystem path to a file:// URL.

    Handles WSL paths (/mnt/c/...) by converting to Windows-style (C:/...)
    since DaVinci Resolve runs on the Windows host.
    """
    abs_str = str(path.resolve())
    # WSL mount path -> Windows drive letter
    if abs_str.startswith("/mnt/") and len(abs_str) > 6 and abs_str[5].isalpha():
        drive = abs_str[5].upper()
        rest = abs_str[6:]  # e.g. "/Videos/..."
        return "file:///" + drive + ":" + rest
    return "file://" + abs_str


def _parse_frame_rate(r_frame_rate: str) -> float:
    """Parse FFmpeg r_frame_rate string like '24000/1001' into fps float."""
    if "/" in r_frame_rate:
        num, den = r_frame_rate.split("/", 1)
    else:
        num, den = r_frame_rate, "1"
    return int(num) / int(den)


def _seconds_to_rational_time(seconds: float, fps: float) -> otio.opentime.RationalTime:
    """Convert seconds to an OTIO RationalTime at the given frame rate."""
    return otio.opentime.RationalTime(round(seconds * fps), fps)


def _build_clip_detections(
    cpd: ClipPlateData,
    src_start_frame: int,
    src_end_frame: int,
) -> dict[str, list[dict]]:
    """Filter and re-key a clip's plate detections into the Fusion/OTIO dict form.

    Keeps only detections whose absolute source-video frame number falls in
    the half-open interval ``[src_start_frame, src_end_frame)``, shifts the
    frame numbers to clip-relative (``frame_num - src_start_frame``), and
    casts all numeric fields to ``float`` so the result is JSON-serialisable.

    Used by both the Fusion Lua generator and the OTIO metadata embedding
    so the two payloads cannot drift.
    """
    result: dict[str, list[dict]] = {}
    for frame_num, boxes in cpd.detections.items():
        if not (src_start_frame <= frame_num < src_end_frame):
            continue
        rel = frame_num - src_start_frame
        result[str(rel)] = [
            {
                "x": float(b.x),
                "y": float(b.y),
                "w": float(b.w),
                "h": float(b.h),
            }
            for b in boxes
        ]
    return result


def _detect_pts_gap_keyframe(
    video_path: Path,
    src_start_frame: int,
    src_end_frame: int,
) -> int | None:
    """Detect if a PTS gap in the source video requires piecewise offset correction.

    Concatenated ("merged") source videos can have a PTS discontinuity at
    the join point.  When Resolve's decoder encounters such a gap, it is
    off by one frame until it resyncs at the next keyframe.  This function
    detects the gap and returns the first keyframe *within the clip's
    content range* so the Lua generator can apply a piecewise correction.

    Returns the absolute source frame number of the first keyframe in
    ``[src_start_frame, src_end_frame)`` if a PTS gap exists before the
    clip, or ``None`` if no correction is needed.
    """
    from trailvideocut.gpu import _find_ffprobe

    ffprobe_bin = _find_ffprobe()
    if ffprobe_bin is None:
        return None

    try:
        result = subprocess.run(
            [
                ffprobe_bin, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "packet=pts,flags",
                "-of", "csv=p=0",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        logger.warning("ffprobe failed for PTS gap detection; skipping correction")
        return None

    if result.returncode != 0:
        return None

    # Single pass: detect PTS gap before the clip AND find the first
    # keyframe within the clip's content range.
    has_gap_before_clip = False
    first_keyframe_in_clip: int | None = None
    expected_delta: int | None = None
    prev_pts: int | None = None
    frame_idx = 0

    for line in result.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            frame_idx += 1
            continue
        try:
            pts = int(parts[0])
        except ValueError:
            frame_idx += 1
            continue
        flags = parts[1] if len(parts) > 1 else ""

        if prev_pts is not None:
            delta = pts - prev_pts
            if expected_delta is None:
                expected_delta = delta
            elif delta != expected_delta and frame_idx <= src_start_frame:
                has_gap_before_clip = True

        # Track keyframes within the clip range
        if (has_gap_before_clip
                and first_keyframe_in_clip is None
                and src_start_frame <= frame_idx < src_end_frame
                and "K" in flags):
            first_keyframe_in_clip = frame_idx

        # Once we've found what we need, stop scanning
        if first_keyframe_in_clip is not None:
            break

        prev_pts = pts
        frame_idx += 1

    if first_keyframe_in_clip is not None:
        logger.info(
            "PTS gap detected before clip [%d, %d); "
            "first keyframe in clip at frame %d",
            src_start_frame, src_end_frame, first_keyframe_in_clip,
        )
    return first_keyframe_in_clip


def _parse_timecode(tc: str | None, fps: float) -> otio.opentime.RationalTime:
    """Parse a SMPTE timecode like '10:23:45:08' into a RationalTime.

    For non-drop timecode, frame numbering uses the nominal (rounded) fps
    (e.g. 24 for 23.976), matching how DaVinci Resolve interprets it.

    Returns RationalTime(0, fps) if tc is None.
    """
    if not tc:
        return otio.opentime.RationalTime(0, fps)
    parts = tc.replace(";", ":").split(":")
    h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    nominal_fps = round(fps)
    total_frames = h * 3600 * nominal_fps + m * 60 * nominal_fps + s * nominal_fps + f
    return otio.opentime.RationalTime(total_frames, fps)


def _generate_otio_timeline(
    plan: CutPlan,
    video_path: Path,
    video_duration: float,
    audio_path: Path,
    r_frame_rate: str,
    timecode: str | None = None,
    plate_data: dict[int, ClipPlateData] | None = None,
    fps: float | None = None,
) -> otio.schema.Timeline:
    """Generate an OTIO Timeline referencing source video with in/out points."""
    if fps is None:
        fps = _parse_frame_rate(r_frame_rate)
    tc_start = _parse_timecode(timecode, fps)

    # Media references — available_range starts at the embedded timecode
    video_media_ref = otio.schema.ExternalReference(
        target_url=_path_to_file_url(video_path),
        available_range=otio.opentime.TimeRange(
            start_time=tc_start,
            duration=_seconds_to_rational_time(video_duration, fps),
        ),
    )

    audio_media_ref = otio.schema.ExternalReference(
        target_url=_path_to_file_url(audio_path),
        available_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, fps),
            duration=_seconds_to_rational_time(plan.total_duration, fps),
        ),
    )

    # Video track — one clip per segment, with optional crossfade transitions
    # source_range start times must be offset by the embedded timecode
    use_crossfade = (
        plan.transition_style == TransitionStyle.CROSSFADE.value
        and len(plan.decisions) > 1
    )
    half_xfade = plan.crossfade_duration / 2.0

    video_track = otio.schema.Track(name="Video", kind=otio.schema.TrackKind.Video)
    clips = []
    for i, d in enumerate(plan.decisions, start=1):
        clip_start = tc_start + _seconds_to_rational_time(d.source_start, fps)
        # Quantise duration from cumulative target frames so the Nth cut lands
        # at round(target_end_N * fps) on the timeline instead of accumulating
        # per-clip rounding error across the song.
        target_start_f = round(d.target_start * fps)
        target_end_f = round(d.target_end * fps)
        duration_frames = max(1, target_end_f - target_start_f)
        clip = otio.schema.Clip(
            name=f"segment_{i:03d}",
            media_reference=video_media_ref.clone(),
            source_range=otio.opentime.TimeRange(
                start_time=clip_start,
                duration=otio.opentime.RationalTime(duration_frames, fps),
            ),
        )

        # Embed plate data as clip metadata
        if plate_data:
            clip_index = i - 1  # decisions are 1-indexed, plate_data is 0-indexed
            cpd = plate_data.get(clip_index)
            if cpd and cpd.detections:
                # Match the round() semantics of _seconds_to_rational_time
                # used for the clip's source_range start so the OTIO clip
                # position and the embedded clip-relative frame numbers
                # agree.
                src_start_frame = int(_seconds_to_rational_time(d.source_start, fps).value)
                src_end_frame = int(_seconds_to_rational_time(d.source_end, fps).value)
                clip_detections = _build_clip_detections(cpd, src_start_frame, src_end_frame)
                if clip_detections:
                    clip.metadata["trailvideocut"] = {
                        "plates": {
                            "fps": fps,
                            "detections": clip_detections,
                        },
                    }

        clips.append(clip)

    if use_crossfade:
        for i, clip in enumerate(clips):
            video_track.append(clip)
            if i < len(clips) - 1:
                d_out = plan.decisions[i]
                d_in = plan.decisions[i + 1]
                out_handle = min(half_xfade, video_duration - d_out.source_end)
                in_handle = min(half_xfade, d_in.source_start)
                if out_handle > 0.01 and in_handle > 0.01:
                    video_track.append(otio.schema.Transition(
                        name=f"dissolve_{i+1:03d}",
                        transition_type=otio.schema.Transition.Type.SMPTE_Dissolve,
                        in_offset=_seconds_to_rational_time(in_handle, fps),
                        out_offset=_seconds_to_rational_time(out_handle, fps),
                    ))
    else:
        for clip in clips:
            video_track.append(clip)

    # Audio track — single clip spanning full duration
    audio_track = otio.schema.Track(name="Audio", kind=otio.schema.TrackKind.Audio)
    audio_track.append(otio.schema.Clip(
        name=audio_path.stem,
        media_reference=audio_media_ref,
        source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, fps),
            duration=_seconds_to_rational_time(plan.total_duration, fps),
        ),
    ))

    timeline = otio.schema.Timeline(name="TrailVideoCut Export")
    timeline.tracks.append(video_track)
    timeline.tracks.append(audio_track)
    return timeline
