"""Post-detection filter stack is invariant under model-variant choice (§6.1).

The `plate-detector-larger-model` change adds runtime selection of the
ONNX backbone (`"n" | "s" | "m"`). A hard requirement is that the filter
stack in `PlateDetector` (geometry → phone-zone gate → vertical-position)
runs identically regardless of which backbone produced the boxes — only
the raw model outputs may differ, never the post-processing.

These tests construct three detectors with three different `model_path`
strings (simulating the three cache filenames the registry hands out) via
the existing `cv2.dnn` mock pattern, then feed hand-crafted box lists
through each internal filter and assert outputs are bit-identical across
variants.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trailvideocut.plate.detector import PlateDetector
from trailvideocut.plate.models import PlateBox


_VARIANT_PATHS = [
    "plate_detector_yolov8n.onnx",   # variant "n"
    "plate_detector_yolov11s.onnx",  # variant "s"
    "plate_detector_yolov11m.onnx",  # variant "m"
]


def _make_detector(path: str, **kwargs) -> PlateDetector:
    """Construct a PlateDetector under the cv2 backend with a mocked reader."""
    with patch("trailvideocut.plate.detector._BACKEND", "cv2"), \
         patch("cv2.dnn.readNetFromONNX") as mock_read:
        mock_read.return_value = MagicMock()
        return PlateDetector(path, **kwargs)


def _detectors_for_all_variants(**kwargs) -> list[PlateDetector]:
    return [_make_detector(p, **kwargs) for p in _VARIANT_PATHS]


class TestGeometryFilterInvariant:
    def test_geometry_accept_set_is_variant_invariant(self):
        # A single box that is well inside all geometry bounds.
        box_ok = PlateBox(x=0.10, y=0.10, w=0.20, h=0.05, confidence=0.9)
        # Too small on a 640x360 frame: 0.005 * 640 = 3.2 px < min_plate_px_w=10.
        box_too_small = PlateBox(x=0.5, y=0.5, w=0.005, h=0.005, confidence=0.9)
        # Bad aspect ratio: 0.10 * 640 / (0.20 * 360) = 64 / 72 = 0.89 — OK
        # Use a truly-square box to trip max_ratio > 1 path:
        box_bad_aspect = PlateBox(x=0.3, y=0.3, w=0.08, h=0.20, confidence=0.9)
        inputs = [box_ok, box_too_small, box_bad_aspect]

        outputs: list[list[PlateBox]] = []
        for det in _detectors_for_all_variants():
            outputs.append(det._filter_geometry(inputs, frame_w=640, frame_h=360))

        # Same kept boxes (by identity) across every variant.
        assert all(len(o) == len(outputs[0]) for o in outputs)
        for o in outputs[1:]:
            assert o == outputs[0]


class TestVerticalPositionFilterInvariant:
    def test_drops_lower_when_upper_present_across_variants(self):
        upper = PlateBox(x=0.1, y=0.2, w=0.05, h=0.05, confidence=0.9)
        lower = PlateBox(x=0.1, y=0.8, w=0.05, h=0.05, confidence=0.9)
        inputs = [upper, lower]

        outputs: list[list[PlateBox]] = []
        for det in _detectors_for_all_variants():
            outputs.append(det._filter_vertical_position(list(inputs)))

        # Every variant keeps only the upper box.
        for o in outputs:
            assert o == [upper]

    def test_keeps_lower_when_no_upper_across_variants(self):
        lower1 = PlateBox(x=0.1, y=0.7, w=0.05, h=0.05, confidence=0.9)
        lower2 = PlateBox(x=0.6, y=0.8, w=0.05, h=0.05, confidence=0.9)
        inputs = [lower1, lower2]

        outputs: list[list[PlateBox]] = []
        for det in _detectors_for_all_variants():
            outputs.append(det._filter_vertical_position(list(inputs)))

        # All variants pass the list through unchanged.
        for o in outputs:
            assert o == inputs


class TestPhoneZoneGateInvariant:
    def test_gate_and_filter_behave_identically_across_variants(self):
        # Upper box survives; lower box falls inside a phone zone and is removed.
        upper = PlateBox(x=0.15, y=0.10, w=0.05, h=0.05, confidence=0.9)
        lower_in_zone = PlateBox(
            x=0.40, y=0.85, w=0.06, h=0.04, confidence=0.9,
        )
        inputs = [upper, lower_in_zone]
        phone_zone = (0.30, 0.80, 0.40, 0.18)  # x, y, w, h — covers lower box

        outputs: list[list[PlateBox]] = []
        gates: list[bool] = []
        for det in _detectors_for_all_variants(exclude_phones=True):
            det._phone_zones = [phone_zone]
            gates.append(det._should_apply_phone_zone_filter(inputs))
            outputs.append(det._filter_phone_zones(list(inputs)))

        # Gate decision is identical (upper present → gate on).
        assert all(g is True for g in gates)
        # Filtered output is identical across variants.
        for o in outputs:
            assert o == [upper]


class TestInvarianceUnderConstructorParams:
    def test_same_params_same_filter_decisions_across_variants(self):
        """Equal per-variant construction → equal filter decisions, end-to-end
        across the gated filter pipeline (geometry → phone-zone → vertical)."""
        # Boxes sized with aspect ≈ 1.4-1.8 on 1920x1080 to satisfy the
        # default geometry filter (min 0.5, max 2.0).
        boxes = [
            # Upper, geometrically OK. 96x54 px → aspect 1.78.
            PlateBox(x=0.20, y=0.15, w=0.05, h=0.05, confidence=0.9),
            # Lower, inside the zone — should be dropped by phone-zone filter.
            PlateBox(x=0.50, y=0.88, w=0.05, h=0.05, confidence=0.9),
            # Lower, outside the zone — vertical-split will drop it because
            # an upper detection survives in the same frame.
            PlateBox(x=0.10, y=0.75, w=0.05, h=0.05, confidence=0.9),
        ]
        phone_zone = (0.40, 0.85, 0.30, 0.12)

        per_variant_results: list[list[PlateBox]] = []
        for det in _detectors_for_all_variants(exclude_phones=True):
            det._phone_zones = [phone_zone]
            step1 = det._filter_geometry(list(boxes), frame_w=1920, frame_h=1080)
            if det._should_apply_phone_zone_filter(step1):
                step1 = det._filter_phone_zones(step1)
            step1 = det._filter_vertical_position(step1)
            per_variant_results.append(step1)

        # All three variants should produce the same surviving list.
        assert all(r == per_variant_results[0] for r in per_variant_results)
        # And that list must be exactly the upper box.
        assert per_variant_results[0] == [boxes[0]]
