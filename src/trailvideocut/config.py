from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TransitionStyle(str, Enum):
    HARD_CUT = "hard_cut"
    CROSSFADE = "crossfade"


@dataclass
class TrailVideoCutConfig:
    """Global configuration for a TrailVideoCut run."""

    video_path: Path
    audio_path: Path
    output_path: Path = field(default_factory=lambda: Path("output.mp4"))

    # Video analysis
    analysis_fps: float = 3.0
    segment_window: float = 2.0
    segment_hop: float = 0.5
    scene_detect_threshold: float = 20.0

    # Audio analysis
    beat_proximity_threshold: float = 0.10  # perceptual minimum gap between beats (seconds)
    beat_strength_threshold: float = 0.3

    # Segment selection
    transition_style: TransitionStyle = TransitionStyle.CROSSFADE
    crossfade_duration: float = 0.2
    min_segment_duration: float = 1.5
    max_segment_duration: float = 8.0
    include_timestamps: list[float] = field(default_factory=list)

    # Energy transition detection
    energy_transition_threshold: float = 0.3  # min energy change (0-1) to force a cut
    energy_smooth_window: float = 1.0  # smoothing window in seconds

    # Quality-adaptive selection
    quality_cv_threshold: float = 0.4
    quality_max_reduction: float = 0.5

    # GPU acceleration
    use_gpu: bool = True
    gpu_batch_size: int = 64

    # Export OTIO for DaVinci Resolve instead of rendering
    davinci: bool = False

    # Plate blur
    plate_blur_enabled: bool = True
    plate_blur_strength: float = 1.0

    # Output
    output_fps: float = 0
    output_codec: str = "libx264"
    output_audio_codec: str = "aac"
    output_preset: str = "veryslow"
    output_threads: int = 0
