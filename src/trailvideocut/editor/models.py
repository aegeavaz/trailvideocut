from dataclasses import dataclass

from trailvideocut.config import TransitionStyle


@dataclass
class EditDecision:
    """A single edit decision: which source segment to use for a beat interval.

    ``source_start`` / ``source_end`` define the clip's core range in seconds.
    The *effective* range used for plate management may extend past
    ``source_end`` into a transition tail — see :func:`clip_frame_window`.
    """

    beat_index: int
    source_start: float
    source_end: float
    target_start: float
    target_end: float
    interest_score: float


@dataclass
class CutPlan:
    """The complete editing plan."""

    decisions: list[EditDecision]
    total_duration: float
    song_tempo: float
    transition_style: str
    crossfade_duration: float = 0.2
    clips_selected: int = 0
    score_cv: float = 0.0


def tail_frames(clip_index: int, plan: CutPlan, fps: float) -> int:
    """Return the number of source-video frames in clip ``clip_index``'s transition tail.

    The tail is ``round(plan.crossfade_duration * fps)`` frames for a
    non-last clip in a CROSSFADE plan, and ``0`` otherwise (CUT plan, last
    clip, zero crossfade duration). Rounding matches the OTIO exporter's
    ``round(seconds * fps)`` convention so UI gates, export filtering, and
    plate keys all agree on what frames belong to the tail.
    """
    if clip_index < 0:
        raise IndexError(clip_index)
    if plan.transition_style != TransitionStyle.CROSSFADE.value:
        return 0
    if plan.crossfade_duration <= 0:
        return 0
    if clip_index >= len(plan.decisions) - 1:
        return 0
    return round(plan.crossfade_duration * fps)


def clip_frame_window(
    clip_index: int, plan: CutPlan, fps: float,
) -> tuple[int, int]:
    """Return ``(start_frame, end_frame_exclusive)`` for clip ``clip_index``.

    The start is the clip's ``source_start`` converted to frames with
    ``round()`` (matching the OTIO exporter). The end is the clip's
    ``source_end`` converted to frames the same way, plus
    :func:`tail_frames` for the clip. The returned interval is half-open:
    ``start_frame <= f < end_frame_exclusive``.
    """
    d = plan.decisions[clip_index]
    start = round(d.source_start * fps)
    end_core = round(d.source_end * fps)
    return (start, end_core + tail_frames(clip_index, plan, fps))
