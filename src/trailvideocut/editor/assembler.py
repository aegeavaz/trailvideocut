import os
import re
import subprocess
import threading
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, BarColumn, TimeRemainingColumn, TextColumn

from moviepy import VideoFileClip, AudioFileClip, ImageClip, concatenate_videoclips
from moviepy.video.fx.CrossFadeIn import CrossFadeIn
from moviepy.video.fx.FadeOut import FadeOut
from moviepy.audio.fx.AudioFadeOut import AudioFadeOut

from trailvideocut.config import TrailVideoCutConfig, TransitionStyle
from trailvideocut.editor.models import CutPlan
from trailvideocut.gpu import _find_ffmpeg, configure_moviepy_ffmpeg, detect_gpu, get_encoder_codec, patch_nvenc_pixel_format
from trailvideocut.plate.models import ClipPlateData

console = Console()


class _MoviePyProgressLogger:
    """Adapts MoviePy's proglog logger interface to a (current, total) callback.

    MoviePy's ``write_videofile`` accepts either ``"bar"`` or a proglog
    ``ProgressBarLogger`` instance.  This lightweight wrapper implements the
    minimal interface that proglog's ``default_bar_logger`` expects so that
    encoding progress is forwarded to the UI.
    """

    def __init__(self, progress_callback):
        self._cb = progress_callback
        self._total = 0

    # proglog calls __call__ for plain messages
    def __call__(self, **kw):
        message = kw.get("message", "")
        if message:
            console.print(f"  {message.strip()}")

    # proglog calls iter_bar for progress iteration
    def iter_bar(self, **kw):
        for bar_name, iterable in kw.items():
            iterable = list(iterable)
            self._total = len(iterable)
            for i, item in enumerate(iterable):
                yield item
                self._cb(i + 1, self._total)

# Map x264 presets to NVENC preset equivalents
_NVENC_PRESET_MAP = {
    "ultrafast": "p1",
    "superfast": "p2",
    "veryfast": "p3",
    "faster": "p4",
    "fast": "p4",
    "medium": "p5",
    "slow": "p6",
    "slower": "p7",
    "veryslow": "p7",
}


def _require_ffmpeg() -> str:
    """Return path to ffmpeg binary or raise RuntimeError."""
    path = detect_gpu().system_ffmpeg or _find_ffmpeg()
    if path is None:
        raise RuntimeError(
            "FFmpeg not found. Install FFmpeg and add it to your system PATH. "
            "Download: https://ffmpeg.org/download.html"
        )
    return path


def _frame_aligned_duration(decision, fps: float) -> float:
    """Return the clip's duration quantised to a whole number of output frames.

    Derived from the music target time so cumulative track position after N
    cuts lands on ``round(target_end_N * fps)`` frames. Falls back to the
    source delta when the target delta is non-positive.
    """
    target_start_f = round(decision.target_start * fps)
    target_end_f = round(decision.target_end * fps)
    frames = target_end_f - target_start_f
    if frames <= 0:
        # Fall back to source-delta quantisation for malformed inputs.
        frames = max(1, round((decision.source_end - decision.source_start) * fps))
    return frames / fps


class VideoAssembler:
    """Assemble the final video from a cut plan."""

    def __init__(
        self,
        config: TrailVideoCutConfig,
        progress_callback: Callable[[int, int], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
    ):
        self.config = config
        self._progress_callback = progress_callback
        self._status_callback = status_callback
        self._blur_temp_files: list[str] = []

    def _get_threads(self) -> int:
        """Return the number of FFmpeg threads to use.

        If output_threads is 0 (auto), use max(4, cpu_count - 2).
        """
        if self.config.output_threads > 0:
            return self.config.output_threads
        cpu = os.cpu_count() or 4
        return max(4, cpu - 2)

    def assemble(
        self,
        plan: CutPlan,
        plate_data: dict[int, ClipPlateData] | None = None,
    ) -> None:
        """Execute the cut plan: extract subclips, concatenate, add audio, export."""
        self._resolve_fps()
        self._blur_temp_files.clear()

        has_blur = (
            plate_data
            and self.config.plate_blur_enabled
            and any(cpd.detections for cpd in plate_data.values())
        )

        # Plate blur is handled by PlateBlurProcessor (deterministic OpenCV
        # frame reading, consistent with the detector and preview).  The
        # FFmpeg paths feed pre-blurred raw YUV segments into the filter
        # graph; MoviePy is kept as a fallback only.
        blur_plate_data = plate_data if has_blur else None

        try:
            if (
                plan.transition_style == TransitionStyle.CROSSFADE.value
                and len(plan.decisions) > 1
            ):
                try:
                    self._assemble_ffmpeg_xfade(plan, blur_plate_data)
                    return
                except Exception as e:
                    console.print(
                        f"  [yellow]FFmpeg xfade failed ({e}), "
                        f"falling back to MoviePy...[/yellow]"
                    )
                    if self._status_callback:
                        self._status_callback("FFmpeg failed, falling back to MoviePy...")
            else:
                try:
                    self._assemble_ffmpeg_hardcut(plan, blur_plate_data)
                    return
                except Exception as e:
                    console.print(
                        f"  [yellow]FFmpeg hardcut failed ({e}), "
                        f"falling back to MoviePy...[/yellow]"
                    )
                    if self._status_callback:
                        self._status_callback("FFmpeg failed, falling back to MoviePy...")
            self._assemble_moviepy(plan, blur_plate_data)
        finally:
            self._cleanup_blur_temps()

    def _cleanup_blur_temps(self) -> None:
        """Remove temporary pre-processed blur segment files."""
        for path in self._blur_temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass
        self._blur_temp_files.clear()

    def _probe_rational_fps(self, source_fps: float) -> str:
        """Probe the source video's exact rational frame rate via FFmpeg.

        Returns a string like ``"24000/1001"`` or ``"30.0"`` suitable for
        FFmpeg's ``-r`` flag.  Falls back to ``str(source_fps)``.
        """
        ffmpeg_bin = _require_ffmpeg()
        rational_fps = str(source_fps)
        try:
            probe = subprocess.run(
                [ffmpeg_bin, "-hide_banner", "-i", str(self.config.video_path)],
                capture_output=True, text=True, timeout=10,
            )
            tbr_match = re.search(
                r"(\d+(?:/\d+)?(?:\.\d+)?)\s+tbr", probe.stderr,
            )
            if tbr_match:
                tbr_str = tbr_match.group(1)
                if "/" in tbr_str:
                    rational_fps = tbr_str
                else:
                    tbr_val = float(tbr_str)
                    for num, den in [(24000, 1001), (30000, 1001), (60000, 1001),
                                     (24, 1), (25, 1), (30, 1), (50, 1), (60, 1)]:
                        if abs(num / den - tbr_val) < 0.02:
                            rational_fps = f"{num}/{den}"
                            break
                    else:
                        rational_fps = tbr_str
                console.print(f"  Source frame rate: {rational_fps}")
        except Exception:
            pass
        return rational_fps

    def _probe_source_video(self) -> tuple[int, int, float, str]:
        """Probe source video dimensions, FPS, and rational FPS.

        Returns ``(width, height, source_fps, rational_fps)``.
        """
        import cv2
        cap = cv2.VideoCapture(str(self.config.video_path))
        fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.release()
        rational_fps = self._probe_rational_fps(source_fps)
        return fw, fh, source_fps, rational_fps

    def _preprocess_blur_segments(
        self,
        segments: list[tuple[float, float, int]],
        plate_data: dict[int, ClipPlateData] | None,
    ) -> tuple[list[tuple[str, float] | None], float]:
        """Pre-process segments that have plate data, returning blurred temp file paths.

        Each segment is ``(start, duration, clip_index)``.
        Returns ``(overrides, source_fps)`` where *overrides* is a list
        parallel to *segments*.  Each element is either:
        - ``(temp_path, exact_duration)`` for a blurred segment, or
        - ``None`` for a segment that needs no blur (use original source).
        """
        if not plate_data or not self.config.plate_blur_enabled:
            return [None] * len(segments), 0.0, ""

        from trailvideocut.editor.exporter import _detect_pts_gap_keyframe
        from trailvideocut.plate.blur import PlateBlurProcessor

        fw, fh, source_fps, rational_fps = self._probe_source_video()

        result: list[tuple[str, float] | None] = []
        for seg_idx, (start, dur, clip_idx) in enumerate(segments):
            cpd = plate_data.get(clip_idx)
            if cpd is None or not cpd.detections:
                result.append(None)
                continue

            # Detect PTS gap for piecewise offset correction (same
            # approach as the DaVinci Lua script's comp_for_rel).
            seg_start_frame = int(start * source_fps)
            seg_end_frame = int((start + dur) * source_fps)
            pts_gap_kf = _detect_pts_gap_keyframe(
                Path(self.config.video_path),
                seg_start_frame,
                seg_end_frame,
            )

            console.print(f"  Pre-processing blur for segment {seg_idx + 1} (clip {clip_idx})...")
            proc = PlateBlurProcessor(
                video_path=str(self.config.video_path),
                segment_start=start,
                segment_duration=dur,
                clip_plate_data=cpd,
                fps=source_fps,
                frame_width=fw,
                frame_height=fh,
                clip_index=clip_idx,
                rational_fps=rational_fps,
                pts_gap_keyframe=pts_gap_kf,
            )
            tmp_path, frames_written = proc.process_segment(
                progress_callback=self._progress_callback,
            )
            self._blur_temp_files.append(str(tmp_path))
            # Compute exact duration from the actual frame count to avoid
            # floating-point drift between the segment duration and the
            # temp file's frame count.
            exact_dur = frames_written / source_fps
            result.append((str(tmp_path), exact_dur))

        return result, source_fps, rational_fps

    # ------------------------------------------------------------------
    # FFmpeg native xfade path (fast)
    # ------------------------------------------------------------------

    def _resolve_fps(self) -> None:
        """Resolve output_fps=0 (auto) by probing the source video."""
        if self.config.output_fps > 0:
            return
        ffmpeg_bin = _require_ffmpeg()
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", str(self.config.video_path)],
            capture_output=True, text=True, timeout=10,
        )
        # Parse "30 fps" or "29.97 fps" or "30 tbr" from ffmpeg stderr
        match = re.search(r"(\d+(?:\.\d+)?)\s+(?:fps|tbr)", result.stderr)
        if match:
            self.config.output_fps = float(match.group(1))
        else:
            self.config.output_fps = 30.0
            console.print("  [yellow]Could not detect source FPS, defaulting to 30[/yellow]")

    def _probe_duration(self, filepath: str) -> float:
        """Probe media file duration using ffmpeg (no ffprobe dependency).

        Runs ``ffmpeg -i <file>`` which prints container metadata (including
        Duration) to stderr and exits immediately with an error because no
        output is specified.  This avoids requiring a separate ffprobe binary.
        """
        ffmpeg_bin = _require_ffmpeg()
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", filepath],
            capture_output=True, text=True, timeout=10,
        )
        # ffmpeg prints "Duration: HH:MM:SS.ff" in stderr
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
        if match:
            h, m, s, frac = match.groups()
            return int(h) * 3600 + int(m) * 60 + int(s) + float(f"0.{frac}")
        raise RuntimeError(f"Could not determine duration of {filepath}")

    def _build_segments(self, plan: CutPlan, source_duration: float):
        """Build list of (start, duration, clip_index) for each segment.

        Quantises each segment's duration to an integer number of output
        frames derived from the music *target* time, so the cumulative
        track position after N cuts lands at ``round(target_end_N * fps)``
        instead of accumulating per-clip rounding error.
        """
        decisions = plan.decisions
        xfade_dur = plan.crossfade_duration
        fps = self.config.output_fps
        xfade_frames = round(xfade_dur * fps) if fps > 0 else 0
        n = len(decisions)
        segments = []
        for i, d in enumerate(decisions):
            start = max(0.0, d.source_start)
            dur = _frame_aligned_duration(d, fps) if fps > 0 else (d.source_end - d.source_start)
            is_last = i == n - 1
            if not is_last and xfade_frames > 0:
                dur = dur + xfade_frames / fps
            # Clamp to available source
            max_dur = max(0.0, source_duration - start)
            if dur > max_dur:
                dur = max_dur
            if dur < 0.05:
                continue
            segments.append((start, dur, i))
        return segments

    def _build_filter_complex(
        self, segments: list[tuple[float, float]],
        audio_input_idx: int, audio_duration: float,
        has_blur_segments: bool = False,
        source_fps: float = 0,
        blur_overrides: list | None = None,
        rational_fps: str = "",
    ) -> str:
        xfade_dur = self.config.crossfade_duration
        n = len(segments)
        filters: list[str] = []

        # When blur segments are mixed with original segments, normalize
        # all inputs so xfade works.
        # Blur segments: use fps with round=zero to avoid the default
        # nearest-rounding which can shift the first frame by 1.
        # Source segments: fps with default rounding + pixel format.
        if has_blur_segments:
            fps_str = rational_fps or str(source_fps if source_fps > 0 else self.config.output_fps)
            for i in range(n):
                is_blur = blur_overrides and blur_overrides[i] is not None
                if is_blur:
                    filters.append(
                        f"[{i}:v]fps={fps_str}[v{i}]"
                    )
                else:
                    filters.append(
                        f"[{i}:v]fps={fps_str},format=yuv420p[v{i}]"
                    )
            input_label = lambda i: f"v{i}"  # noqa: E731
        else:
            input_label = lambda i: f"{i}:v"  # noqa: E731

        # --- A) Chain xfade filters ---
        if n == 1:
            final_label = input_label(0)
            cumulative = segments[0][1]
        else:
            cumulative = segments[0][1]
            prev_label = input_label(0)
            for i in range(1, n):
                offset = cumulative - xfade_dur
                if offset < 0:
                    offset = 0.0
                out_label = f"vx{i}" if i < n - 1 else "vout"
                filters.append(
                    f"[{prev_label}][{input_label(i)}]xfade=transition=fade"
                    f":duration={xfade_dur:.6f}:offset={offset:.6f}[{out_label}]"
                )
                prev_label = out_label
                cumulative = offset + segments[i][1]
            final_label = prev_label

        # --- B) Freeze-frame padding if video < audio ---
        video_total = cumulative
        if video_total < audio_duration - 0.01:
            deficit = audio_duration - video_total
            filters.append(
                f"[{final_label}]tpad=stop_mode=clone"
                f":stop_duration={deficit:.6f}[vpadded]"
            )
            final_label = "vpadded"

        # --- C) Trim to audio duration + video fade-out ---
        fade_dur = min(2.0, audio_duration * 0.1)
        fade_start = audio_duration - fade_dur
        filters.append(
            f"[{final_label}]trim=start=0:end={audio_duration:.6f},"
            f"setpts=PTS-STARTPTS,"
            f"fade=t=out:st={fade_start:.6f}:d={fade_dur:.6f}[vfinal]"
        )

        # --- D) Audio: trim + fade-out ---
        filters.append(
            f"[{audio_input_idx}:a]atrim=start=0:end={audio_duration:.6f},"
            f"asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={fade_start:.6f}:d={fade_dur:.6f}[afinal]"
        )

        return ";".join(filters)

    def _assemble_ffmpeg_xfade(
        self,
        plan: CutPlan,
        plate_data: dict[int, ClipPlateData] | None = None,
    ) -> None:
        """Assemble video using FFmpeg native xfade filter (fast path).

        Uses per-segment input seeking (-ss/-t) instead of trim filters
        to avoid decoding the entire source once per segment.
        """
        source_duration = self._probe_duration(str(self.config.video_path))
        audio_duration = self._probe_duration(str(self.config.audio_path))

        segments = self._build_segments(plan, source_duration)
        if not segments:
            raise RuntimeError("No valid segments for FFmpeg assembly")

        blur_overrides, source_fps, rational_fps = self._preprocess_blur_segments(segments, plate_data)
        has_blur = any(b is not None for b in blur_overrides)

        # When a blurred temp file replaces a source segment, use the
        # temp file's exact duration (computed from its frame count)
        # instead of the original segment duration, to avoid frame-count
        # drift in the filter graph.
        effective_segments = []
        for i, (start, dur, clip_idx) in enumerate(segments):
            override = blur_overrides[i]
            if override is not None:
                _tmp_path, exact_dur = override
                effective_segments.append((start, exact_dur, clip_idx))
            else:
                effective_segments.append((start, dur, clip_idx))

        audio_input_idx = len(segments)

        filter_complex = self._build_filter_complex(
            effective_segments, audio_input_idx, audio_duration,
            has_blur_segments=has_blur,
            source_fps=source_fps,
            blur_overrides=blur_overrides,
            rational_fps=rational_fps,
        )

        codec = get_encoder_codec(force_cpu=not self.config.use_gpu)
        is_nvenc = codec == "h264_nvenc"

        frac = Fraction(self.config.output_fps).limit_denominator(100000)
        fps_str = f"{frac.numerator}/{frac.denominator}"

        ffmpeg_bin = _require_ffmpeg()
        cmd = [ffmpeg_bin, "-y"]

        # Per-segment inputs: source video with fast seeking, or
        # pre-blurred raw YUV files from PlateBlurProcessor.
        video_path = str(self.config.video_path)
        fps_str_rational = rational_fps or str(source_fps)

        if has_blur:
            import cv2 as _cv2
            _cap = _cv2.VideoCapture(video_path)
            fw = int(_cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
            fh = int(_cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
            _cap.release()

        for i, (start, dur, _clip_idx) in enumerate(segments):
            override = blur_overrides[i]
            if override is not None:
                tmp_path, _exact_dur = override
                cmd.extend([
                    "-f", "rawvideo",
                    "-pix_fmt", "yuv420p",
                    "-s", f"{fw}x{fh}",
                    "-r", fps_str_rational,
                    "-i", tmp_path,
                ])
            else:
                cmd.extend(["-ss", f"{start:.6f}", "-t", f"{dur:.6f}", "-i", video_path])

        # Audio input (last input)
        cmd.extend(["-i", str(self.config.audio_path)])

        # Filter complex
        cmd.extend(["-filter_complex", filter_complex])

        # Map outputs
        cmd.extend(["-map", "[vfinal]", "-map", "[afinal]"])

        # Video encoding
        cmd.extend(["-c:v", codec, "-r", fps_str])

        if is_nvenc:
            nvenc_preset = _NVENC_PRESET_MAP.get(self.config.output_preset, "p5")
            cmd.extend([
                "-preset", nvenc_preset,
                "-rc", "vbr", "-cq", "23",
                "-pix_fmt", "yuv420p",
            ])
            console.print(
                f"  Exporting to {self.config.output_path} "
                f"(FFmpeg xfade + NVENC, preset {nvenc_preset})..."
            )
        else:
            cmd.extend([
                "-preset", self.config.output_preset,
                "-pix_fmt", "yuv420p",
            ])
            console.print(
                f"  Exporting to {self.config.output_path} "
                f"(FFmpeg xfade + libx264)..."
            )

        # Audio encoding
        cmd.extend(["-c:a", self.config.output_audio_codec])

        # Threading
        cmd.extend(["-threads", str(self._get_threads())])

        # Output
        cmd.append(str(self.config.output_path))

        console.print(
            f"  Running FFmpeg xfade assembly "
            f"({len(segments)} segments)..."
        )

        # Add -progress pipe:1 for machine-readable progress on stdout
        cmd.extend(["-progress", "pipe:1"])

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        self._track_ffmpeg_progress(proc, audio_duration)

    # ------------------------------------------------------------------
    # FFmpeg native hard-cut path (fast)
    # ------------------------------------------------------------------

    def _build_segments_hardcut(self, plan: CutPlan, source_duration: float):
        """Build list of (start, duration, clip_index) for hard-cut segments.

        Quantises each segment's duration to an integer number of output
        frames derived from the music *target* time, so the cumulative
        track position after N cuts lands at ``round(target_end_N * fps)``
        instead of accumulating per-clip rounding error.
        """
        fps = self.config.output_fps
        segments = []
        for i, d in enumerate(plan.decisions):
            start = max(0.0, d.source_start)
            dur = _frame_aligned_duration(d, fps) if fps > 0 else (d.source_end - d.source_start)
            max_dur = max(0.0, source_duration - start)
            if dur > max_dur:
                dur = max_dur
            if dur < 0.05:
                continue
            segments.append((start, dur, i))
        return segments

    def _build_filter_complex_hardcut(
        self, segments: list[tuple[float, float]],
        audio_input_idx: int, audio_duration: float,
        has_blur_segments: bool = False,
        source_fps: float = 0,
        blur_overrides: list | None = None,
        rational_fps: str = "",
    ) -> str:
        n = len(segments)
        filters: list[str] = []

        # See _build_filter_complex for rationale.
        if has_blur_segments:
            fps_str = rational_fps or str(source_fps if source_fps > 0 else self.config.output_fps)
            for i in range(n):
                is_blur = blur_overrides and blur_overrides[i] is not None
                if is_blur:
                    filters.append(
                        f"[{i}:v]fps={fps_str}[v{i}]"
                    )
                else:
                    filters.append(f"[{i}:v]fps={fps_str},format=yuv420p[v{i}]")
            concat_inputs = "".join(f"[v{i}]" for i in range(n))
        else:
            concat_inputs = "".join(f"[{i}:v]" for i in range(n))

        # --- A) Concat all video segments ---
        filters.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vconcat]")
        final_label = "vconcat"

        # --- B) Freeze-frame padding if video < audio ---
        video_total = sum(seg[1] for seg in segments)
        if video_total < audio_duration - 0.01:
            deficit = audio_duration - video_total
            filters.append(
                f"[{final_label}]tpad=stop_mode=clone"
                f":stop_duration={deficit:.6f}[vpadded]"
            )
            final_label = "vpadded"

        # --- C) Trim to audio duration + video fade-out ---
        fade_dur = min(2.0, audio_duration * 0.1)
        fade_start = audio_duration - fade_dur
        filters.append(
            f"[{final_label}]trim=start=0:end={audio_duration:.6f},"
            f"setpts=PTS-STARTPTS,"
            f"fade=t=out:st={fade_start:.6f}:d={fade_dur:.6f}[vfinal]"
        )

        # --- D) Audio: trim + fade-out ---
        filters.append(
            f"[{audio_input_idx}:a]atrim=start=0:end={audio_duration:.6f},"
            f"asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={fade_start:.6f}:d={fade_dur:.6f}[afinal]"
        )

        return ";".join(filters)

    def _assemble_ffmpeg_hardcut(
        self,
        plan: CutPlan,
        plate_data: dict[int, ClipPlateData] | None = None,
    ) -> None:
        """Assemble video using FFmpeg concat filter (hard-cut, no crossfade)."""
        source_duration = self._probe_duration(str(self.config.video_path))
        audio_duration = self._probe_duration(str(self.config.audio_path))

        segments = self._build_segments_hardcut(plan, source_duration)
        if not segments:
            raise RuntimeError("No valid segments for FFmpeg assembly")

        blur_overrides, source_fps, rational_fps = self._preprocess_blur_segments(segments, plate_data)
        has_blur = any(b is not None for b in blur_overrides)

        # Use exact temp file durations for the filter graph
        effective_segments = []
        for i, (start, dur, clip_idx) in enumerate(segments):
            override = blur_overrides[i]
            if override is not None:
                _tmp_path, exact_dur = override
                effective_segments.append((start, exact_dur, clip_idx))
            else:
                effective_segments.append((start, dur, clip_idx))

        audio_input_idx = len(segments)

        filter_complex = self._build_filter_complex_hardcut(
            effective_segments, audio_input_idx, audio_duration,
            has_blur_segments=has_blur,
            source_fps=source_fps,
            blur_overrides=blur_overrides,
            rational_fps=rational_fps,
        )

        codec = get_encoder_codec(force_cpu=not self.config.use_gpu)
        is_nvenc = codec == "h264_nvenc"

        frac = Fraction(self.config.output_fps).limit_denominator(100000)
        fps_str = f"{frac.numerator}/{frac.denominator}"

        ffmpeg_bin = _require_ffmpeg()
        cmd = [ffmpeg_bin, "-y"]

        # Per-segment inputs (raw YUV for blurred, source for others).
        fps_str_rational = rational_fps or str(source_fps)
        video_path = str(self.config.video_path)

        if has_blur:
            import cv2 as _cv2
            _cap = _cv2.VideoCapture(video_path)
            fw = int(_cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
            fh = int(_cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
            _cap.release()

        for i, (start, dur, _clip_idx) in enumerate(segments):
            override = blur_overrides[i]
            if override is not None:
                tmp_path, _exact_dur = override
                cmd.extend([
                    "-f", "rawvideo",
                    "-pix_fmt", "yuv420p",
                    "-s", f"{fw}x{fh}",
                    "-r", fps_str_rational,
                    "-i", tmp_path,
                ])
            else:
                cmd.extend(["-ss", f"{start:.6f}", "-t", f"{dur:.6f}", "-i", video_path])

        # Audio input (last input)
        cmd.extend(["-i", str(self.config.audio_path)])

        # Filter complex
        cmd.extend(["-filter_complex", filter_complex])

        # Map outputs
        cmd.extend(["-map", "[vfinal]", "-map", "[afinal]"])

        # Video encoding
        cmd.extend(["-c:v", codec, "-r", fps_str])

        if is_nvenc:
            nvenc_preset = _NVENC_PRESET_MAP.get(self.config.output_preset, "p5")
            cmd.extend([
                "-preset", nvenc_preset,
                "-rc", "vbr", "-cq", "23",
                "-pix_fmt", "yuv420p",
            ])
            console.print(
                f"  Exporting to {self.config.output_path} "
                f"(FFmpeg hardcut + NVENC, preset {nvenc_preset})..."
            )
        else:
            cmd.extend([
                "-preset", self.config.output_preset,
                "-pix_fmt", "yuv420p",
            ])
            console.print(
                f"  Exporting to {self.config.output_path} "
                f"(FFmpeg hardcut + libx264)..."
            )

        # Audio encoding
        cmd.extend(["-c:a", self.config.output_audio_codec])

        # Threading
        cmd.extend(["-threads", str(self._get_threads())])

        # Output
        cmd.append(str(self.config.output_path))

        console.print(
            f"  Running FFmpeg hardcut assembly "
            f"({len(segments)} segments)..."
        )

        # Add -progress pipe:1 for machine-readable progress on stdout
        cmd.extend(["-progress", "pipe:1"])

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        self._track_ffmpeg_progress(proc, audio_duration)

    def _track_ffmpeg_progress(self, proc: subprocess.Popen, total_duration: float) -> None:
        """Parse FFmpeg -progress output and display a Rich progress bar."""
        stderr_chunks: list[bytes] = []
        total_safe = max(1, int(total_duration))

        def drain_stderr() -> None:
            for chunk in proc.stderr:
                stderr_chunks.append(chunk)

        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        stderr_thread.start()

        with Progress(
            TextColumn("  [cyan]Encoding"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("encoding", total=total_duration)
            for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace").strip()
                if line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        seconds = us / 1_000_000
                        progress.update(task, completed=min(seconds, total_duration))
                        if self._progress_callback:
                            self._progress_callback(int(seconds), total_safe)
                    except (ValueError, IndexError):
                        pass
                elif line == "progress=end":
                    progress.update(task, completed=total_duration)
                    if self._progress_callback:
                        self._progress_callback(total_safe, total_safe)

        proc.wait()
        stderr_thread.join(timeout=5)

        if proc.returncode != 0:
            err_text = b"".join(stderr_chunks).decode(errors="replace")
            # Log the full stderr for debugging
            console.print("  [red]FFmpeg stderr (last 2000 chars):[/red]")
            console.print(err_text[-2000:])
            raise RuntimeError(
                f"FFmpeg exit {proc.returncode}: {err_text[-500:] or 'no stderr'}"
            )

    # ------------------------------------------------------------------
    # MoviePy path (fallback)
    # ------------------------------------------------------------------

    def _assemble_moviepy(
        self,
        plan: CutPlan,
        plate_data: dict[int, ClipPlateData] | None = None,
    ) -> None:
        """Assemble video using MoviePy (fallback for hard-cut or xfade failure)."""
        source_clip = VideoFileClip(str(self.config.video_path))
        audio_clip = AudioFileClip(str(self.config.audio_path))

        try:
            subclips_with_idx = self._extract_subclips(source_clip, plan)

            if not subclips_with_idx:
                raise RuntimeError("No valid subclips produced from cut plan")

            # Fallback blur via MoviePy transform() with calibrated offset +
            # expanded boxes.  The primary FFmpeg path uses PlateBlurProcessor
            # which is deterministic; this path is a best-effort fallback.
            if plate_data and self.config.plate_blur_enabled:
                import cv2 as _cv2
                from trailvideocut.plate.blur import (
                    apply_blur_to_frame,
                    calibrate_frame_offset,
                    expand_boxes_for_drift,
                )

                _cap = _cv2.VideoCapture(str(self.config.video_path))
                source_fps = _cap.get(_cv2.CAP_PROP_FPS) or 30.0
                _cap.release()

                console.print(
                    "  [yellow]FFmpeg blur failed, using MoviePy fallback "
                    "(drift-tolerant but less precise)[/yellow]"
                )
                console.print(f"  [cyan]MoviePy blur[/cyan] fps={source_fps}")

                def _make_blur_fn(cpd_ref, calibrated_start, fps_val):
                    """Apply drift-expanded blur to each frame."""
                    def blur_fn(get_frame, t):
                        frame = get_frame(t)
                        abs_frame = calibrated_start + round(t * fps_val)
                        boxes = expand_boxes_for_drift(
                            cpd_ref.detections, abs_frame, margin_frames=1,
                        )
                        if boxes:
                            frame = frame.copy()
                            apply_blur_to_frame(frame, boxes)
                        return frame
                    return blur_fn

                blurred = []
                for sub, clip_idx in subclips_with_idx:
                    cpd = plate_data.get(clip_idx)
                    if cpd and cpd.detections:
                        decision = plan.decisions[clip_idx]
                        expected_frame = round(decision.source_start * source_fps)

                        # Calibrate: compare MoviePy's first frame with source
                        moviepy_frame = sub.get_frame(0)
                        moviepy_bgr = moviepy_frame[:, :, ::-1].copy()
                        frame_offset = calibrate_frame_offset(
                            moviepy_bgr,
                            str(self.config.video_path),
                            expected_frame,
                            search_range=3,
                        )
                        calibrated_start = expected_frame + frame_offset

                        console.print(
                            f"  Blur clip {clip_idx}: "
                            f"expected={expected_frame} offset={frame_offset} "
                            f"calibrated={calibrated_start}"
                        )

                        sub = sub.transform(
                            _make_blur_fn(cpd, calibrated_start, source_fps),
                        )
                    blurred.append((sub, clip_idx))
                subclips_with_idx = blurred

            subclips = [sc for sc, _ in subclips_with_idx]

            console.print(f"  Concatenating {len(subclips)} clips...")

            if plan.transition_style == TransitionStyle.CROSSFADE.value and len(subclips) > 1:
                for i in range(1, len(subclips)):
                    subclips[i] = subclips[i].with_effects([CrossFadeIn(plan.crossfade_duration)])
                final_video = concatenate_videoclips(
                    subclips, method="compose", padding=-plan.crossfade_duration
                )
            else:
                final_video = concatenate_videoclips(subclips)

            # Match video duration to full song length
            audio_duration = audio_clip.duration

            if final_video.duration < audio_duration:
                deficit = audio_duration - final_video.duration
                console.print(f"  Extending video by {deficit:.1f}s to match song duration...")
                last_frame = final_video.get_frame(final_video.duration - 0.01)
                freeze = ImageClip(last_frame, duration=deficit)
                final_video = concatenate_videoclips([final_video, freeze])

            # Trim to exact audio duration (handles video > audio case)
            final_video = final_video.subclipped(0, audio_duration)

            # Smooth fade-out ending (video fades to black, audio fades to silence)
            fade_dur = min(2.0, audio_duration * 0.1)
            final_video = final_video.with_effects([FadeOut(fade_dur)])
            trimmed_audio = audio_clip.subclipped(0, audio_duration)
            trimmed_audio = trimmed_audio.with_effects([AudioFadeOut(fade_dur)])
            final_video = final_video.with_audio(trimmed_audio)

            # Select encoder: NVENC when GPU available + use_gpu, else libx264
            codec = get_encoder_codec(force_cpu=not self.config.use_gpu)
            is_nvenc = codec == "h264_nvenc"

            # Switch moviepy to system ffmpeg (the bundled one lacks NVENC)
            # and fix the yuva420p pixel format that moviepy hardcodes
            if is_nvenc:
                configure_moviepy_ffmpeg()
                patch_nvenc_pixel_format()

            if is_nvenc:
                nvenc_preset = _NVENC_PRESET_MAP.get(self.config.output_preset, "p5")
                console.print(
                    f"  Exporting to {self.config.output_path} "
                    f"(NVENC, preset {nvenc_preset})..."
                )
            else:
                console.print(f"  Exporting to {self.config.output_path} (libx264)...")

            # When blur is active, write at source FPS so MoviePy iterates
            # at exactly 1 source frame per output frame (no resampling).
            frac = Fraction(self.config.output_fps).limit_denominator(100000)
            fps_rational = f"{frac.numerator}/{frac.denominator}"

            ffmpeg_params = ["-r", fps_rational]
            preset = self.config.output_preset

            if is_nvenc:
                nvenc_preset = _NVENC_PRESET_MAP.get(self.config.output_preset, "p5")
                preset = nvenc_preset
                # -pix_fmt yuv420p overrides moviepy's hardcoded yuva420p
                # (last -pix_fmt wins in ffmpeg)
                ffmpeg_params.extend([
                    "-rc", "vbr", "-cq", "23", "-pix_fmt", "yuv420p",
                ])

            # Use a custom logger that forwards progress to the UI callback
            if self._progress_callback:
                mp_logger = _MoviePyProgressLogger(self._progress_callback)
            else:
                mp_logger = "bar"

            final_video.write_videofile(
                str(self.config.output_path),
                fps=self.config.output_fps,
                codec=codec,
                audio_codec=self.config.output_audio_codec,
                preset=preset,
                threads=self._get_threads(),
                ffmpeg_params=ffmpeg_params,
                logger=mp_logger,
            )
        finally:
            source_clip.close()
            audio_clip.close()

    def _extract_subclips(
        self, source_clip: VideoFileClip, plan: CutPlan,
    ) -> list[tuple]:
        """Extract subclips from the source video based on edit decisions.

        Returns a list of ``(subclip, clip_index)`` tuples so callers can
        map each subclip back to its position in ``plan.decisions``.
        """
        use_crossfade = (
            plan.transition_style == TransitionStyle.CROSSFADE.value
            and len(plan.decisions) > 1
        )
        subclips = []
        for i, decision in enumerate(plan.decisions):
            start = max(0, decision.source_start)
            end = min(source_clip.duration, decision.source_end)
            # Extend non-last clips to compensate for crossfade overlap
            if use_crossfade and i < len(plan.decisions) - 1:
                end = min(source_clip.duration, end + plan.crossfade_duration)
            if end - start < 0.05:
                continue
            sub = source_clip.subclipped(start, end)
            subclips.append((sub, i))
        return subclips
