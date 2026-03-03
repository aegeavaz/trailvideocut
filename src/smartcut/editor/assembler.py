import os
from fractions import Fraction

from rich.console import Console

from moviepy import VideoFileClip, AudioFileClip, ImageClip, concatenate_videoclips
from moviepy.video.fx.CrossFadeIn import CrossFadeIn
from moviepy.video.fx.FadeOut import FadeOut
from moviepy.audio.fx.AudioFadeOut import AudioFadeOut

from smartcut.config import SmartCutConfig, TransitionStyle
from smartcut.editor.models import CutPlan
from smartcut.gpu import configure_moviepy_ffmpeg, get_encoder_codec, patch_nvenc_pixel_format

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


class VideoAssembler:
    """Assemble the final video from a cut plan."""

    def __init__(self, config: SmartCutConfig):
        self.config = config

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
