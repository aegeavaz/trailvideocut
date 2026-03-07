from dataclasses import dataclass


@dataclass
class EditDecision:
    """A single edit decision: which source segment to use for a beat interval."""

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
