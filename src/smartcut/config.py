from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TransitionStyle(str, Enum):
    HARD_CUT = "hard_cut"
    CROSSFADE = "crossfade"


@dataclass
class SmartCutConfig:
    """Global configuration for a SmartCut run."""

    video_path: Path
    audio_path: Path
    output_path: Path = field(default_factory=lambda: Path("output.mp4"))

    # Video analysis
    analysis_fps: float = 3.0
    segment_window: float = 2.0
    segment_hop: float = 0.5
    scene_detect_threshold: float = 20.0

    # Audio analysis
    beat_strength_threshold: float = 0.3

    # Segment selection
    transition_style: TransitionStyle = TransitionStyle.HARD_CUT
    crossfade_duration: float = 0.08
    min_segment_duration: float = 0.25
    max_segment_duration: float = 8.0
    include_timestamps: list[float] = field(default_factory=list)

    # GPU acceleration
    use_gpu: bool = True
    gpu_batch_size: int = 64

    # Output
    output_fps: float = 0
    output_codec: str = "libx264"
    output_audio_codec: str = "aac"
    output_preset: str = "medium"
    output_threads: int = 0
