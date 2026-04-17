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

    # Debug-only: phone exclusion zones active on each frame during detection.
    # Keyed by frame number; each value is a list of (x, y, w, h) normalized
    # tuples. Not persisted to sidecar files (see plate/storage.py).
    phone_zones: dict[int, list[tuple[float, float, float, float]]] = field(
        default_factory=dict,
    )
