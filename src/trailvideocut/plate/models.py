from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class PlateBox:
    """A single detected license plate bounding box in normalized coordinates (0-1).

    An ``angle`` of 0.0 denotes an axis-aligned rectangle. A non-zero ``angle``
    (degrees, counter-clockwise) denotes an oriented rectangle whose centre is
    the centre of the axis-aligned ``(x, y, w, h)`` rectangle and whose
    plate-aligned extents are ``w`` and ``h`` (i.e. the box's own, not the
    envelope's, width and height).
    """

    x: float  # left of the plate-aligned rectangle, normalized
    y: float  # top of the plate-aligned rectangle, normalized
    w: float  # plate-aligned width, normalized
    h: float  # plate-aligned height, normalized
    confidence: float = 0.0
    manual: bool = False
    angle: float = 0.0  # degrees, counter-clockwise; 0 = axis-aligned

    def aabb_envelope(self) -> tuple[float, float, float, float]:
        """Return the axis-aligned bounding box enclosing this (possibly rotated)
        rectangle, in normalized coordinates ``(x, y, w, h)``.

        For ``angle == 0`` this is the box itself.
        """
        if self.angle == 0.0:
            return (self.x, self.y, self.w, self.h)
        cx = self.x + self.w / 2.0
        cy = self.y + self.h / 2.0
        rad = math.radians(self.angle)
        cos_a = abs(math.cos(rad))
        sin_a = abs(math.sin(rad))
        env_w = self.w * cos_a + self.h * sin_a
        env_h = self.w * sin_a + self.h * cos_a
        return (cx - env_w / 2.0, cy - env_h / 2.0, env_w, env_h)

    def corners_px(self, widget_w: float, widget_h: float) -> list[tuple[float, float]]:
        """Return the four corners of this (possibly rotated) rectangle as
        ``(x_px, y_px)`` tuples in the given pixel canvas.

        Corners are returned in a consistent order (TL → TR → BR → BL of the
        plate-aligned rectangle before rotation).
        """
        cx = (self.x + self.w / 2.0) * widget_w
        cy = (self.y + self.h / 2.0) * widget_h
        half_w = (self.w * widget_w) / 2.0
        half_h = (self.h * widget_h) / 2.0
        rad = math.radians(self.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        local = (
            (-half_w, -half_h),
            (half_w, -half_h),
            (half_w, half_h),
            (-half_w, half_h),
        )
        corners: list[tuple[float, float]] = []
        for lx, ly in local:
            rx = lx * cos_a - ly * sin_a
            ry = lx * sin_a + ly * cos_a
            corners.append((cx + rx, cy + ry))
        return corners


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
