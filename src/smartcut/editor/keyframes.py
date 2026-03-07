import json
import subprocess


def probe_video_params(video_path: str) -> dict:
    """Probe width, height, r_frame_rate, pix_fmt from the first video stream."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt,profile,level:stream_tags=timecode:format=duration",
            "-print_format", "json",
            str(video_path),
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError(f"No video stream found in {video_path}")
    s = streams[0]
    # Map ffprobe level_idc (e.g. 31) to ffmpeg format (e.g. "3.1")
    # Only pass known H.264 levels; skip non-standard values
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
        "timecode": s.get("tags", {}).get("timecode"),
    }
