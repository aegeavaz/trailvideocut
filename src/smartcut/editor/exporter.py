from pathlib import Path

import opentimelineio as otio
from rich.console import Console

from smartcut.config import SmartCutConfig
from smartcut.editor.keyframes import probe_video_params
from smartcut.editor.models import CutPlan

console = Console()


class DaVinciExporter:
    """Export an OTIO timeline referencing source video and audio directly."""

    def __init__(self, config: SmartCutConfig):
        self.config = config

    def export(self, plan: CutPlan) -> Path:
        video_path = self.config.video_path
        vparams = probe_video_params(str(video_path))

        r_frame_rate = vparams.get("r_frame_rate", "24000/1001")
        video_duration = vparams.get("duration", 0.0)
        timecode = vparams.get("timecode")

        otio_path = video_path.parent / "project.otio"
        timeline = _generate_otio_timeline(
            plan, video_path, video_duration,
            self.config.audio_path, r_frame_rate, timecode,
        )
        timeline.to_json_file(str(otio_path))
        console.print(f"  OTIO: {otio_path}")
        console.print(f"  {len(plan.decisions)} segments referenced from source video")
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
) -> otio.schema.Timeline:
    """Generate an OTIO Timeline referencing source video with in/out points."""
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

    # Video track — one clip per segment
    # source_range start times must be offset by the embedded timecode
    video_track = otio.schema.Track(name="Video", kind=otio.schema.TrackKind.Video)
    for i, d in enumerate(plan.decisions, start=1):
        clip_start = tc_start + _seconds_to_rational_time(d.source_start, fps)
        clip = otio.schema.Clip(
            name=f"segment_{i:03d}",
            media_reference=video_media_ref.clone(),
            source_range=otio.opentime.TimeRange(
                start_time=clip_start,
                duration=_seconds_to_rational_time(d.source_end - d.source_start, fps),
            ),
        )
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

    timeline = otio.schema.Timeline(name="SmartCut Export")
    timeline.tracks.append(video_track)
    timeline.tracks.append(audio_track)
    return timeline
