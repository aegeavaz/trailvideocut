from dataclasses import dataclass, field

import numpy as np


@dataclass
class BeatInfo:
    """A single detected beat."""

    timestamp: float
    strength: float
    is_downbeat: bool = False


@dataclass
class MusicSection:
    """A structural section of the song."""

    label: str
    start_time: float
    end_time: float
    energy: float


@dataclass
class AudioAnalysis:
    """Complete audio analysis result."""

    duration: float
    tempo: float
    beats: list[BeatInfo]
    sections: list[MusicSection] = field(default_factory=list)
    onset_envelope: np.ndarray = field(default_factory=lambda: np.array([]))
    sample_rate: int = 22050
