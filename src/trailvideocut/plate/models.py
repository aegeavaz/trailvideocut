from dataclasses import dataclass, field


@dataclass
class PlateBox:
    """A single detected license plate bounding box in normalized coordinates (0-1)."""

    x: float  # left
    y: float  # top
    w: float  # width
    h: float  # height
    confidence: float = 0.0
    manual: bool = False


@dataclass
class ClipPlateData:
    """Plate detection results for a single clip."""

    clip_index: int
    detections: dict[int, list[PlateBox]] = field(default_factory=dict)
    # frame_number -> list of boxes
