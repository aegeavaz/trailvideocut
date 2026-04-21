"""Tests for the manual-plate position projector."""

import pytest

from trailvideocut.plate.models import PlateBox
from trailvideocut.plate.projection import project_manual_box


def _box(cx: float, cy: float, w: float = 0.10, h: float = 0.05) -> PlateBox:
    """Build a box from its normalized center and size."""
    return PlateBox(x=cx - w / 2, y=cy - h / 2, w=w, h=h)


def _center(box: PlateBox) -> tuple[float, float]:
    return (box.x + box.w / 2, box.y + box.h / 2)


class TestProjectManualBoxFallbacks:
    def test_zero_detections_returns_none(self):
        assert project_manual_box({}, current_frame=10) is None

    def test_single_detection_returns_none(self):
        detections = {20: [_box(0.5, 0.5)]}
        assert project_manual_box(detections, current_frame=30) is None

    def test_gap_exceeds_max_window_returns_none(self):
        # Both reference frames are further than max_window from current frame.
        detections = {0: [_box(0.3, 0.5)], 5: [_box(0.35, 0.5)]}
        assert project_manual_box(detections, current_frame=200, max_window=60) is None


class TestProjectManualBoxTwoPrior:
    def test_linear_extrapolation_forward(self):
        # Plate moving +0.005 x-per-frame. At frame 60 we expect 0.50.
        detections = {
            40: [_box(0.40, 0.50)],
            50: [_box(0.45, 0.50)],
        }
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        cx, cy = _center(box)
        assert cx == pytest.approx(0.50, abs=1e-9)
        assert cy == pytest.approx(0.50, abs=1e-9)
        assert box.manual is False  # caller decides manual flag; projector returns geometry only

    def test_size_taken_from_nearest_reference(self):
        near = _box(0.45, 0.50, w=0.12, h=0.07)
        far = _box(0.40, 0.50, w=0.20, h=0.10)
        detections = {40: [far], 50: [near]}
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        assert box.w == pytest.approx(near.w)
        assert box.h == pytest.approx(near.h)

    def test_prefers_two_prior_over_prior_plus_next(self):
        # Two priors available → use those, not prior+next.
        # Priors give velocity +0.01 x-per-frame; next would give a different answer.
        detections = {
            40: [_box(0.30, 0.50)],
            50: [_box(0.40, 0.50)],
            80: [_box(0.10, 0.50)],
        }
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        cx, _ = _center(box)
        assert cx == pytest.approx(0.50, abs=1e-9)


class TestProjectManualBoxInterpolation:
    def test_interpolates_between_prior_and_next(self):
        # Current frame is halfway between references — expect midpoint.
        detections = {
            50: [_box(0.40, 0.40)],
            60: [_box(0.50, 0.60)],
        }
        box = project_manual_box(detections, current_frame=55)
        assert box is not None
        cx, cy = _center(box)
        assert cx == pytest.approx(0.45, abs=1e-9)
        assert cy == pytest.approx(0.50, abs=1e-9)

    def test_interpolation_size_from_nearest(self):
        # Current frame 52 is closer to frame 50 → size from frame 50's box.
        close = _box(0.40, 0.40, w=0.11, h=0.06)
        far = _box(0.50, 0.60, w=0.20, h=0.10)
        detections = {50: [close], 60: [far]}
        box = project_manual_box(detections, current_frame=52)
        assert box is not None
        assert box.w == pytest.approx(close.w)
        assert box.h == pytest.approx(close.h)


class TestProjectManualBoxTwoNext:
    def test_backward_extrapolation(self):
        # No priors. Velocity from frames 20→30 is +0.05 x-per-10-frames.
        # Projecting back to frame 10 → 0.40 - 0.05 = 0.35.
        detections = {
            20: [_box(0.40, 0.50)],
            30: [_box(0.45, 0.50)],
        }
        box = project_manual_box(detections, current_frame=10)
        assert box is not None
        cx, _ = _center(box)
        assert cx == pytest.approx(0.35, abs=1e-9)


class TestProjectManualBoxClamping:
    def test_clamps_right_edge(self):
        # Velocity would put the right edge past 1.0 — clamp so box stays in [0, 1].
        detections = {
            40: [_box(0.80, 0.50, w=0.20)],
            50: [_box(0.90, 0.50, w=0.20)],
        }
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        assert box.x >= 0.0
        assert box.x + box.w <= 1.0 + 1e-9

    def test_clamps_left_edge(self):
        detections = {
            40: [_box(0.20, 0.50, w=0.20)],
            50: [_box(0.10, 0.50, w=0.20)],
        }
        box = project_manual_box(detections, current_frame=80)
        assert box is not None
        assert box.x >= 0.0
        assert box.x + box.w <= 1.0 + 1e-9

    def test_clamps_bottom_edge(self):
        detections = {
            40: [_box(0.50, 0.85, h=0.10)],
            50: [_box(0.50, 0.92, h=0.10)],
        }
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        assert box.y >= 0.0
        assert box.y + box.h <= 1.0 + 1e-9


class TestProjectManualBoxPicksFirstBoxPerFrame:
    def test_uses_first_box_when_multiple_per_frame(self):
        # Matches find_nearest_reference_box semantics: take index 0.
        detections = {
            40: [_box(0.40, 0.50), _box(0.70, 0.50)],
            50: [_box(0.45, 0.50), _box(0.80, 0.50)],
        }
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        cx, _ = _center(box)
        assert cx == pytest.approx(0.50, abs=1e-9)


class TestProjectManualBoxSpecScenarios:
    """Named mappings from `specs/plate-overlay-ui/spec.md` scenarios to the
    projector behavior that implements them.
    """

    def test_spec_projection_with_two_prior_detections(self):
        # Scenario: Projection with two prior detections
        detections = {40: [_box(0.40, 0.50)], 50: [_box(0.45, 0.50)]}
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        assert _center(box)[0] == pytest.approx(0.50, abs=1e-9)

    def test_spec_projection_clamps_to_frame_bounds(self):
        # Scenario: Projection clamps to frame bounds
        detections = {
            40: [_box(0.90, 0.50, w=0.15)],
            50: [_box(0.95, 0.50, w=0.15)],
        }
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        assert 0.0 <= box.x and box.x + box.w <= 1.0 + 1e-9

    def test_spec_projection_between_prior_and_next(self):
        # Scenario: Projection between prior and next detections
        detections = {50: [_box(0.40, 0.50)], 60: [_box(0.50, 0.50)]}
        box = project_manual_box(detections, current_frame=55)
        assert box is not None
        assert _center(box)[0] == pytest.approx(0.45, abs=1e-9)

    def test_spec_projection_only_next_side(self):
        # Scenario: Projection with only next-side detections
        detections = {20: [_box(0.40, 0.50)], 30: [_box(0.45, 0.50)]}
        box = project_manual_box(detections, current_frame=10)
        assert box is not None
        assert _center(box)[0] == pytest.approx(0.35, abs=1e-9)

    def test_spec_projection_window_exceeded_returns_none(self):
        # Scenario: Projection gap exceeds the motion window → caller falls back to clone.
        detections = {0: [_box(0.5, 0.5)], 5: [_box(0.5, 0.5)]}
        assert project_manual_box(detections, current_frame=200, max_window=60) is None

    def test_spec_only_one_reference_returns_none(self):
        # Scenario: Only one reference detection → caller falls back to clone.
        detections = {20: [_box(0.5, 0.5)]}
        assert project_manual_box(detections, current_frame=25) is None


class TestProjectManualBoxAngleInheritance:
    """fix-plate-box-handlers: projected box carries the nearest reference's
    rotation so the manual add path can match surrounding plates instead of
    snapping to axis-aligned."""

    def test_projected_angle_matches_nearest_reference(self):
        near = PlateBox(x=0.45 - 0.06, y=0.5 - 0.035, w=0.12, h=0.07, angle=15.0)
        far = PlateBox(x=0.40 - 0.10, y=0.5 - 0.05, w=0.20, h=0.10, angle=-5.0)
        detections = {40: [far], 50: [near]}
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        # Nearest reference for frame 60 is frame 50 → angle 15°.
        assert box.angle == pytest.approx(15.0)

    def test_clamped_projection_preserves_angle(self):
        # Force clamping (centre would push envelope outside [0,1]) and
        # verify the angle survives the _clamp_box path.
        detections = {
            40: [PlateBox(x=0.80, y=0.50, w=0.20, h=0.10, angle=10.0)],
            50: [PlateBox(x=0.90, y=0.50, w=0.20, h=0.10, angle=10.0)],
        }
        box = project_manual_box(detections, current_frame=60)
        assert box is not None
        assert box.angle == pytest.approx(10.0)


class TestProjectManualBoxTransitionTail:
    """plate-clip-transition-tail: projection must work across the clip's
    core/tail boundary. Projection is frame-agnostic, so these tests pin that
    behaviour as a regression guard against future "restrict to core range"
    refactors.
    """

    def test_target_in_tail_with_core_reference(self):
        # Clip core ends at frame 120, tail is frames 120..125 inclusive.
        # Manual add at frame 123 with the only reference at frame 118.
        # Only one reference exists → projector returns None; the caller
        # falls back to nearest-clone. The test below covers that path
        # at the review-page integration level. Here we prove that adding
        # a second reference from inside the core range yields projection.
        detections = {
            100: [PlateBox(x=0.40, y=0.50, w=0.10, h=0.05, angle=10.0)],
            118: [PlateBox(x=0.49, y=0.50, w=0.10, h=0.05, angle=10.0)],
        }
        box = project_manual_box(detections, current_frame=123)
        assert box is not None
        cx, _ = _center(box)
        # Velocity per-frame: (0.54 - 0.45)/(118-100) = 0.005; projected
        # centre at frame 123: 0.54 + 5*0.005 = 0.565.
        assert cx == pytest.approx(0.565, abs=1e-9)
        assert box.angle == pytest.approx(10.0)

    def test_target_in_core_with_only_tail_references(self):
        # Only existing detections are inside the tail; projection still
        # operates on absolute frame keys.
        detections = {
            122: [PlateBox(x=0.55, y=0.50, w=0.10, h=0.05, angle=8.0)],
            124: [PlateBox(x=0.57, y=0.50, w=0.10, h=0.05, angle=8.0)],
        }
        box = project_manual_box(detections, current_frame=119)
        assert box is not None
        cx, _ = _center(box)
        # Centres: 0.60 at 122, 0.62 at 124. Velocity +0.01/frame; at frame
        # 119 (3 frames before 122) centre = 0.60 - 3*0.01 = 0.57.
        assert cx == pytest.approx(0.57, abs=1e-9)
        assert box.angle == pytest.approx(8.0)


class TestProjectManualBoxNoQtImport:
    def test_module_has_no_qt_dependency(self):
        import sys

        import trailvideocut.plate.projection  # noqa: F401

        for name in list(sys.modules):
            if name.startswith("PySide6") or name.startswith("PyQt"):
                # If Qt is already imported by another test, we can't fully prove absence.
                # But we assert nothing *new* is pulled in by the projection module — the
                # import above should succeed without needing Qt in the first place.
                pass
        # The real guarantee is that the module source imports nothing from Qt.
        src = trailvideocut.plate.projection.__file__
        with open(src, encoding="utf-8") as f:
            text = f.read()
        assert "PySide6" not in text
        assert "PyQt" not in text
