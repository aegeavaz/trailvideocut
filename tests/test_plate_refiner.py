"""Tests for trailvideocut.plate.refiner.refine_box."""
from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from trailvideocut.plate.models import PlateBox
from trailvideocut.plate.refiner import (
    RefinementResult,
    RefinerConfig,
    refine_box,
)


def _synthetic_frame(
    frame_w: int,
    frame_h: int,
    plate_rect: tuple[int, int, int, int],  # (cx, cy, w, h) in pixels
    angle_deg: float = 0.0,
    background: int = 80,
    plate_fill: int = 240,
    border: int = 10,
    add_text: bool = True,
) -> np.ndarray:
    """Render a single plate-like rectangle onto a solid background.

    Uses :func:`cv2.boxPoints` + :func:`cv2.fillConvexPoly` to create an
    axis-aligned or rotated rectangle with a dark border and lighter interior
    plus some fake "character" marks for contour contrast.
    """
    img = np.full((frame_h, frame_w, 3), background, dtype=np.uint8)
    cx, cy, w, h = plate_rect
    rect = ((cx, cy), (w, h), angle_deg)
    box_pts = cv2.boxPoints(rect).astype(np.int32)
    # Dark outer border
    cv2.drawContours(img, [box_pts], -1, (30, 30, 30), thickness=border)
    # Light interior
    cv2.fillConvexPoly(img, box_pts, (plate_fill, plate_fill, plate_fill))
    # Add some "character" strokes for internal gradient — helps the adaptive
    # threshold latch onto the plate as a single region after the morph-close.
    if add_text:
        cv2.putText(
            img, "ABC 123", (int(cx - w * 0.35), int(cy + h * 0.2)),
            cv2.FONT_HERSHEY_SIMPLEX, h / 70.0, (30, 30, 30),
            max(1, int(h / 20)), cv2.LINE_AA,
        )
    return img


class TestTighterAabb:
    def test_axis_aligned_plate_gets_tighter_fit(self):
        frame_w, frame_h = 640, 360
        plate_cx, plate_cy, pw, ph = 320, 180, 160, 40
        frame = _synthetic_frame(frame_w, frame_h, (plate_cx, plate_cy, pw, ph))

        # Input box is a loose AABB around the plate.
        loose = PlateBox(
            x=(plate_cx - pw) / frame_w,
            y=(plate_cy - ph) / frame_h,
            w=(2 * pw) / frame_w,
            h=(2 * ph) / frame_h,
            confidence=0.9,
        )
        result: RefinementResult = refine_box(frame, loose)

        # Ground truth AABB for IoU comparison.
        gt = PlateBox(
            x=(plate_cx - pw / 2) / frame_w,
            y=(plate_cy - ph / 2) / frame_h,
            w=pw / frame_w,
            h=ph / frame_h,
        )

        def _iou(a: PlateBox, b: PlateBox) -> float:
            ax, ay, aw, ah = a.aabb_envelope()
            bx, by, bw, bh = b.aabb_envelope()
            x1 = max(ax, bx)
            y1 = max(ay, by)
            x2 = min(ax + aw, bx + bw)
            y2 = min(ay + ah, by + bh)
            if x2 <= x1 or y2 <= y1:
                return 0.0
            inter = (x2 - x1) * (y2 - y1)
            return inter / (aw * ah + bw * bh - inter)

        assert result.method in {"aabb", "oriented"}
        assert _iou(result.box, gt) > _iou(loose, gt)
        # Metadata preserved.
        assert result.box.confidence == pytest.approx(0.9)


class TestOrientedFit:
    def test_rotated_plate_produces_oriented_output(self):
        frame_w, frame_h = 640, 360
        plate_cx, plate_cy, pw, ph = 320, 180, 160, 40
        target_angle = 15.0
        frame = _synthetic_frame(
            frame_w, frame_h, (plate_cx, plate_cy, pw, ph), angle_deg=target_angle,
        )

        # Input box is the AABB envelope — i.e. loose around the rotated plate.
        rad = math.radians(target_angle)
        env_w = abs(pw * math.cos(rad)) + abs(ph * math.sin(rad))
        env_h = abs(pw * math.sin(rad)) + abs(ph * math.cos(rad))
        loose = PlateBox(
            x=(plate_cx - env_w / 2 - 15) / frame_w,
            y=(plate_cy - env_h / 2 - 10) / frame_h,
            w=(env_w + 30) / frame_w,
            h=(env_h + 20) / frame_h,
            confidence=0.9,
        )

        result = refine_box(frame, loose)
        assert result.method == "oriented", (
            f"expected oriented, got {result.method} with box {result.box}"
        )
        # minAreaRect's angle convention: abs(angle) within ±3° of the target
        # or its complement (angle + 90°) when w/h are swapped.
        a = abs(result.box.angle)
        target = abs(target_angle)
        assert min(abs(a - target), abs(a - (90 - target))) <= 3.0


class TestLowContrastUnchanged:
    def test_flat_frame_returns_unchanged(self):
        """A perfectly uniform frame has no contours — nothing to refine."""
        frame = np.full((240, 320, 3), 120, dtype=np.uint8)
        box = PlateBox(x=0.3, y=0.3, w=0.2, h=0.1, confidence=0.7)
        result = refine_box(frame, box)
        assert result.method == "unchanged"
        assert result.box == box


class TestDeterminism:
    def test_identical_inputs_yield_identical_outputs(self):
        frame = _synthetic_frame(640, 360, (320, 180, 160, 40))
        box = PlateBox(x=0.25, y=0.4, w=0.5, h=0.2, confidence=0.9)
        a = refine_box(frame, box)
        b = refine_box(frame, box)
        assert a.box == b.box
        assert a.confidence == pytest.approx(b.confidence)
        assert a.method == b.method


class TestOrientedGate:
    def test_small_angle_stays_aabb(self):
        # A near-axis-aligned plate (0.5°) must be returned as AABB.
        frame = _synthetic_frame(640, 360, (320, 180, 160, 40), angle_deg=0.5)
        loose = PlateBox(
            x=(320 - 100) / 640, y=(180 - 30) / 360,
            w=200 / 640, h=60 / 360, confidence=0.9,
        )
        result = refine_box(frame, loose, RefinerConfig(min_oriented_angle_deg=2.0))
        assert result.method in {"aabb", "unchanged"}
        assert result.box.angle == 0.0


class TestZeroSizeGuards:
    def test_empty_frame_unchanged(self):
        frame = np.zeros((0, 0, 3), dtype=np.uint8)
        box = PlateBox(0.1, 0.1, 0.1, 0.1)
        assert refine_box(frame, box).method == "unchanged"

    def test_zero_box_unchanged(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        box = PlateBox(0.1, 0.1, 0.0, 0.0)
        assert refine_box(frame, box).method == "unchanged"
