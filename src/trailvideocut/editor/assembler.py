import json
import os
import re
import subprocess
import threading
from fractions import Fraction

from rich.console import Console
from rich.progress import Progress, BarColumn, TimeRemainingColumn, TextColumn

from moviepy import VideoFileClip, AudioFileClip, ImageClip, concatenate_videoclips
from moviepy.video.fx.CrossFadeIn import CrossFadeIn
from moviepy.video.fx.FadeOut import FadeOut
from moviepy.audio.fx.AudioFadeOut import AudioFadeOut

from trailvideocut.config import TrailVideoCutConfig, TransitionStyle
from trailvideocut.editor.models import CutPlan
from trailvideocut.gpu import _find_ffmpeg, configure_moviepy_ffmpeg, detect_gpu, get_encoder_codec, patch_nvenc_pixel_format

console = Console()

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


class VideoAssembler:
    """Assemble the final video from a cut plan."""

    def __init__(
        self,
        config: TrailVideoCutConfig,
        progress_callback: "Callable[[int, int], None] | None" = None,
    ):
        self.config = config
        self._progress_callback = progress_callback

    def _get_threads(self) -> int:
        """Return the number of FFmpeg threads to use.

        If output_threads is 0 (auto), use max(4, cpu_count - 2).
        """
        if self.config.output_threads > 0:
            return self.config.output_threads
        cpu = os.cpu_count() or 4
        return max(4, cpu - 2)

    def assemble(self, plan: CutPlan) -> None:
        """Execute the cut plan: extract subclips, concatenate, add audio, export."""
        self._resolve_fps()
        if (
            plan.transition_style == TransitionStyle.CROSSFADE.value
            and len(plan.decisions) > 1
        ):
            try:
                self._assemble_ffmpeg_xfade(plan)
                return
            except Exception as e:
                console.print(
                    f"  [yellow]FFmpeg xfade failed ({e}), "
                    f"falling back to MoviePy...[/yellow]"
                )
        else:
            try:
                self._assemble_ffmpeg_hardcut(plan)
                return
            except Exception as e:
                console.print(
                    f"  [yellow]FFmpeg hardcut failed ({e}), "
                    f"falling back to MoviePy...[/yellow]"
                )
        self._assemble_moviepy(plan)

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
        """Build list of (start, duration) for each segment."""
        decisions = plan.decisions
        xfade_dur = plan.crossfade_duration
        n = len(decisions)
        segments = []
        for i, d in enumerate(decisions):
            start = max(0.0, d.source_start)
            end = min(source_duration, d.source_end)
            is_last = i == n - 1
            if not is_last:
                end = min(source_duration, end + xfade_dur)
            dur = end - start
            if dur < 0.05:
                continue
            segments.append((start, dur))
        return segments

    def _build_filter_complex(
        self, segments: list[tuple[float, float]],
        audio_input_idx: int, audio_duration: float,
    ) -> str:
        xfade_dur = self.config.crossfade_duration
        n = len(segments)
        filters: list[str] = []

        # Each segment is a separate input, so [0:v], [1:v], etc.
        # Audio is input index `audio_input_idx`

        # --- A) Chain xfade filters ---
        if n == 1:
            final_label = "0:v"
            cumulative = segments[0][1]
        else:
            cumulative = segments[0][1]
            prev_label = "0:v"
            for i in range(1, n):
                offset = cumulative - xfade_dur
                if offset < 0:
                    offset = 0.0
                out_label = f"vx{i}" if i < n - 1 else "vout"
                filters.append(
                    f"[{prev_label}][{i}:v]xfade=transition=fade"
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

    def _assemble_ffmpeg_xfade(self, plan: CutPlan) -> None:
        """Assemble video using FFmpeg native xfade filter (fast path).

        Uses per-segment input seeking (-ss/-t) instead of trim filters
        to avoid decoding the entire source once per segment.
        """
        source_duration = self._probe_duration(str(self.config.video_path))
        audio_duration = self._probe_duration(str(self.config.audio_path))

        segments = self._build_segments(plan, source_duration)
        if not segments:
            raise RuntimeError("No valid segments for FFmpeg assembly")

        audio_input_idx = len(segments)

        filter_complex = self._build_filter_complex(
            segments, audio_input_idx, audio_duration,
        )

        codec = get_encoder_codec(force_cpu=not self.config.use_gpu)
        is_nvenc = codec == "h264_nvenc"

        frac = Fraction(self.config.output_fps).limit_denominator(100000)
        fps_str = f"{frac.numerator}/{frac.denominator}"

        ffmpeg_bin = _require_ffmpeg()
        cmd = [ffmpeg_bin, "-y"]

        # Per-segment inputs with fast seeking
        video_path = str(self.config.video_path)
        for start, dur in segments:
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
        """Build list of (start, duration) for hard-cut segments (no xfade extension)."""
        segments = []
        for d in plan.decisions:
            start = max(0.0, d.source_start)
            end = min(source_duration, d.source_end)
            dur = end - start
            if dur < 0.05:
                continue
            segments.append((start, dur))
        return segments

    def _build_filter_complex_hardcut(
        self, segments: list[tuple[float, float]],
        audio_input_idx: int, audio_duration: float,
    ) -> str:
        n = len(segments)
        filters: list[str] = []

        # --- A) Concat all video segments ---
        concat_inputs = "".join(f"[{i}:v]" for i in range(n))
        filters.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vconcat]")
        final_label = "vconcat"

        # --- B) Freeze-frame padding if video < audio ---
        video_total = sum(dur for _, dur in segments)
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

    def _assemble_ffmpeg_hardcut(self, plan: CutPlan) -> None:
        """Assemble video using FFmpeg concat filter (hard-cut, no crossfade)."""
        source_duration = self._probe_duration(str(self.config.video_path))
        audio_duration = self._probe_duration(str(self.config.audio_path))

        segments = self._build_segments_hardcut(plan, source_duration)
        if not segments:
            raise RuntimeError("No valid segments for FFmpeg assembly")

        audio_input_idx = len(segments)

        filter_complex = self._build_filter_complex_hardcut(
            segments, audio_input_idx, audio_duration,
        )

        codec = get_encoder_codec(force_cpu=not self.config.use_gpu)
        is_nvenc = codec == "h264_nvenc"

        frac = Fraction(self.config.output_fps).limit_denominator(100000)
        fps_str = f"{frac.numerator}/{frac.denominator}"

        ffmpeg_bin = _require_ffmpeg()
        cmd = [ffmpeg_bin, "-y"]

        # Per-segment inputs with fast seeking
        video_path = str(self.config.video_path)
        for start, dur in segments:
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
            raise RuntimeError(
                f"FFmpeg exit {proc.returncode}: {err_text[-500:] or 'no stderr'}"
            )

    # ------------------------------------------------------------------
    # MoviePy path (fallback)
    # ------------------------------------------------------------------

    def _assemble_moviepy(self, plan: CutPlan) -> None:
        """Assemble video using MoviePy (fallback for hard-cut or xfade failure)."""
        source_clip = VideoFileClip(str(self.config.video_path))
        audio_clip = AudioFileClip(str(self.config.audio_path))

        try:
            subclips = self._extract_subclips(source_clip, plan)

            if not subclips:
                raise RuntimeError("No valid subclips produced from cut plan")

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

            final_video.write_videofile(
                str(self.config.output_path),
                fps=self.config.output_fps,
                codec=codec,
                audio_codec=self.config.output_audio_codec,
                preset=preset,
                threads=self._get_threads(),
                ffmpeg_params=ffmpeg_params,
                logger="bar",
            )
        finally:
            source_clip.close()
            audio_clip.close()

    def _extract_subclips(self, source_clip: VideoFileClip, plan: CutPlan) -> list:
        """Extract subclips from the source video based on edit decisions."""
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
            subclips.append(sub)
        return subclips
