"""Tests for PlateBox data model — covers the refine-plate-box-fit extensions.

Group 1 (data-model) tasks from openspec change refine-plate-box-fit.
"""
from __future__ import annotations

import math

import pytest

from trailvideocut.plate.models import PlateBox


class TestAngleField:
    def test_angle_defaults_to_zero(self):
        box = PlateBox(x=0.1, y=0.2, w=0.3, h=0.15)
        assert box.angle == 0.0

    def test_angle_accepts_user_value(self):
        box = PlateBox(x=0.1, y=0.2, w=0.3, h=0.15, angle=12.5)
        assert box.angle == pytest.approx(12.5)

    def test_negative_angle_accepted(self):
        box = PlateBox(x=0.1, y=0.2, w=0.3, h=0.15, angle=-27.0)
        assert box.angle == pytest.approx(-27.0)

    def test_equality_considers_all_fields(self):
        a = PlateBox(0.1, 0.2, 0.3, 0.15, confidence=0.9, manual=True, angle=10.0)
        b = PlateBox(0.1, 0.2, 0.3, 0.15, confidence=0.9, manual=True, angle=10.0)
        c = PlateBox(0.1, 0.2, 0.3, 0.15, confidence=0.9, manual=True, angle=11.0)
        assert a == b
        assert a != c

    def test_equality_axis_aligned_without_explicit_angle(self):
        a = PlateBox(0.1, 0.2, 0.3, 0.15, confidence=0.9, manual=False)
        b = PlateBox(0.1, 0.2, 0.3, 0.15, confidence=0.9, manual=False, angle=0.0)
        assert a == b


class TestAabbEnvelope:
    def test_axis_aligned_envelope_is_self(self):
        box = PlateBox(x=0.2, y=0.3, w=0.4, h=0.1)
        env = box.aabb_envelope()
        assert env == pytest.approx((0.2, 0.3, 0.4, 0.1))

    def test_axis_aligned_envelope_ignores_zero_angle(self):
        box = PlateBox(x=0.2, y=0.3, w=0.4, h=0.1, angle=0.0)
        env = box.aabb_envelope()
        assert env == pytest.approx((0.2, 0.3, 0.4, 0.1))

    def test_90_degree_rotation_swaps_extents(self):
        # 0.4-wide, 0.1-tall plate centred at (0.5, 0.5). Rotated 90° it becomes
        # 0.1-wide, 0.4-tall in the envelope — centre preserved.
        box = PlateBox(x=0.3, y=0.45, w=0.4, h=0.1, angle=90.0)
        ex, ey, ew, eh = box.aabb_envelope()
        # envelope centre (ex + ew/2, ey + eh/2) should equal box centre (0.5, 0.5)
        assert (ex + ew / 2) == pytest.approx(0.5, abs=1e-6)
        assert (ey + eh / 2) == pytest.approx(0.5, abs=1e-6)
        assert ew == pytest.approx(0.1, abs=1e-6)
        assert eh == pytest.approx(0.4, abs=1e-6)

    def test_45_degree_rotation_expands_envelope(self):
        # Square 0.2x0.2 centred at (0.5, 0.5), rotated 45° — envelope side
        # should be 0.2*sqrt(2).
        box = PlateBox(x=0.4, y=0.4, w=0.2, h=0.2, angle=45.0)
        ex, ey, ew, eh = box.aabb_envelope()
        expected_side = 0.2 * math.sqrt(2)
        assert ew == pytest.approx(expected_side, abs=1e-6)
        assert eh == pytest.approx(expected_side, abs=1e-6)
        assert (ex + ew / 2) == pytest.approx(0.5, abs=1e-6)
        assert (ey + eh / 2) == pytest.approx(0.5, abs=1e-6)


class TestCornersPx:
    def test_axis_aligned_corners_map_to_rectangle(self):
        # 200x100 widget; box at (0.1, 0.2) with size (0.5, 0.4) -> pixel
        # rectangle from (20, 20) to (120, 60).
        box = PlateBox(x=0.1, y=0.2, w=0.5, h=0.4)
        corners = box.corners_px(200, 100)
        assert len(corners) == 4
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        assert min(xs) == pytest.approx(20.0, abs=1e-6)
        assert max(xs) == pytest.approx(120.0, abs=1e-6)
        assert min(ys) == pytest.approx(20.0, abs=1e-6)
        assert max(ys) == pytest.approx(60.0, abs=1e-6)

    def test_rotated_90_corners(self):
        # Square box; 90° rotation leaves corners on the same four pixel points
        # as the axis-aligned rectangle, just in a different cyclical order.
        box_aa = PlateBox(x=0.4, y=0.4, w=0.2, h=0.2, angle=0.0)
        box_rot = PlateBox(x=0.4, y=0.4, w=0.2, h=0.2, angle=90.0)
        c_aa = sorted((round(c[0], 6), round(c[1], 6)) for c in box_aa.corners_px(100, 100))
        c_rot = sorted(
            (round(c[0], 6), round(c[1], 6)) for c in box_rot.corners_px(100, 100)
        )
        assert c_aa == c_rot

    def test_rotated_45_corner_distance_to_centre(self):
        # Square 40x40 centred at (50, 50); 45° rotation keeps corner distance
        # to centre equal to sqrt(20^2 + 20^2).
        box = PlateBox(x=0.3, y=0.3, w=0.4, h=0.4, angle=45.0)
        corners = box.corners_px(100, 100)
        import math as _math
        for cx, cy in corners:
            dist = _math.hypot(cx - 50.0, cy - 50.0)
            assert dist == pytest.approx(_math.sqrt(800), abs=1e-6)
