import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from smartcut.gpu import _find_ffmpeg

logger = logging.getLogger(__name__)


def _find_ffprobe() -> str | None:
    """Find the ffprobe binary: derive from ffmpeg path, then fall back to PATH.

    Returns None if ffprobe is not available (e.g. imageio-ffmpeg bundles
    only ffmpeg without ffprobe).
    """
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        p = Path(ffmpeg)
        ffprobe = str(p.with_name(p.name.replace("ffmpeg", "ffprobe")))
        if shutil.which(ffprobe) or Path(ffprobe).exists():
            return ffprobe
    path = shutil.which("ffprobe")
    if path:
        return path
    return None


def _extract_timecode_ffmpeg(video_path: str) -> str | None:
    """Extract timecode from video metadata using ffmpeg -i (stderr parsing).

    This is useful when ffprobe is not available but ffmpeg is (e.g. via
    imageio-ffmpeg).  Returns the timecode string or None.
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(video_path)],
            capture_output=True, text=True, timeout=10,
        )
        # ffmpeg -i always exits non-zero when no output file is given,
        # but metadata is printed to stderr regardless.
        m = re.search(r"timecode\s*:\s*(\d{2}:\d{2}:\d{2}[;:]\d{2})", result.stderr)
        return m.group(1) if m else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _probe_video_params_ffprobe(video_path: str) -> dict | None:
    """Probe video parameters using ffprobe. Returns None on failure."""
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "quiet",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt,profile,level:stream_tags=timecode:format=duration:format_tags=timecode",
                "-print_format", "json",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            return None
        s = streams[0]
        _VALID_LEVELS = {
            10, 11, 12, 13, 20, 21, 22, 30, 31, 32, 40, 41, 42, 50, 51, 52,
        }
        raw_level = s.get("level", 0)
        if raw_level in _VALID_LEVELS:
            level_str = f"{raw_level // 10}.{raw_level % 10}"
        else:
            level_str = None

        codec = s.get("codec_name", "h264")
        fmt = data.get("format", {})
        duration = float(fmt.get("duration", 0))

        return {
            "codec_name": codec,
            "width": int(s["width"]),
            "height": int(s["height"]),
            "r_frame_rate": s["r_frame_rate"],
            "pix_fmt": s.get("pix_fmt", "yuv420p"),
            "profile": s.get("profile", "").lower().replace(" ", ""),
            "level": level_str,
            "duration": duration,
            "timecode": s.get("tags", {}).get("timecode") or fmt.get("tags", {}).get("timecode"),
        }
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _probe_video_params_cv2(video_path: str) -> dict | None:
    """Fallback: probe basic video parameters using cv2.VideoCapture."""
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or width <= 0 or height <= 0:
            return None
        duration = total_frames / fps if total_frames > 0 and fps > 0 else 0.0
        # Express fps as a fraction string (e.g. "30000/1001")
        from fractions import Fraction
        frac = Fraction(fps).limit_denominator(100000)
        r_frame_rate = f"{frac.numerator}/{frac.denominator}"
        return {
            "codec_name": "h264",
            "width": width,
            "height": height,
            "r_frame_rate": r_frame_rate,
            "pix_fmt": "yuv420p",
            "profile": "",
            "level": None,
            "duration": duration,
            "timecode": None,
        }
    finally:
        cap.release()


def probe_video_params(video_path: str) -> dict:
    """Probe video parameters, trying ffprobe first then cv2 as fallback."""
    result = _probe_video_params_ffprobe(video_path)
    if result is not None:
        return result
    logger.info("ffprobe not available, falling back to cv2 for video info")
    result = _probe_video_params_cv2(video_path)
    if result is not None:
        if result["timecode"] is None:
            tc = _extract_timecode_ffmpeg(video_path)
            if tc:
                result["timecode"] = tc
        return result
    raise RuntimeError(
        f"Cannot read video parameters from {video_path}. "
        "Install FFmpeg or ensure OpenCV can read the file."
    )
