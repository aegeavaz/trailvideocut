import os
from fractions import Fraction

from rich.console import Console

from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

from smartcut.config import SmartCutConfig, TransitionStyle
from smartcut.editor.models import CutPlan

console = Console()


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
                    subclips[i] = subclips[i].crossfadein(plan.crossfade_duration)
                final_video = concatenate_videoclips(
                    subclips, padding=-plan.crossfade_duration
                )
            else:
                final_video = concatenate_videoclips(subclips)

            # Replace audio with the song
            song_duration = min(audio_clip.duration, final_video.duration)
            trimmed_audio = audio_clip.subclipped(0, song_duration)
            final_video = final_video.with_audio(trimmed_audio)

            console.print(f"  Exporting to {self.config.output_path}...")
            frac = Fraction(self.config.output_fps).limit_denominator(100000)
            fps_rational = f"{frac.numerator}/{frac.denominator}"
            final_video.write_videofile(
                str(self.config.output_path),
                fps=self.config.output_fps,
                codec=self.config.output_codec,
                audio_codec=self.config.output_audio_codec,
                preset=self.config.output_preset,
                threads=self._get_threads(),
                ffmpeg_params=["-r", fps_rational],
                logger="bar",
            )
        finally:
            source_clip.close()
            audio_clip.close()

    def _extract_subclips(self, source_clip: VideoFileClip, plan: CutPlan) -> list:
        """Extract subclips from the source video based on edit decisions."""
        subclips = []
        for decision in plan.decisions:
            start = max(0, decision.source_start)
            end = min(source_clip.duration, decision.source_end)
            if end - start < 0.05:
                continue
            sub = source_clip.subclipped(start, end)
            subclips.append(sub)
        return subclips
