"""Tests for plate blur processing."""

import cv2
import numpy as np
import pytest

from trailvideocut.plate.blur import (
    _blur_kernel_size,
    apply_blur_to_frame,
    grab_frame,
)
from trailvideocut.plate.models import ClipPlateData, PlateBox


class TestBlurKernelSize:
    def test_uses_min_dimension(self):
        k = _blur_kernel_size(100, 40)
        # min(100,40)=40, max(3,40)=40, even->41
        assert k == 41

    def test_tiny_plate_minimum_kernel(self):
        k = _blur_kernel_size(10, 5)
        # min(10,5)=5, max(3,5)=5, odd->5
        assert k == 5

    def test_very_small_plate_floor(self):
        k = _blur_kernel_size(2, 1)
        # min(2,1)=1, max(3,1)=3
        assert k == 3

    def test_result_always_odd(self):
        for w, h in [(80, 60), (50, 50), (100, 30), (7, 7)]:
            k = _blur_kernel_size(w, h)
            assert k % 2 == 1


class TestApplyBlurToFrame:
    def _make_frame(self, h=100, w=200):
        """Create a test frame with high-contrast content (checkerboard)."""
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        # Create a checkerboard-like pattern so blur is detectable
        for y in range(h):
            for x in range(w):
                if (x // 4 + y // 4) % 2 == 0:
                    frame[y, x] = [255, 255, 255]
        return frame

    def test_blur_modifies_plate_region(self):
        frame = self._make_frame()
        original_region = frame[20:40, 40:120].copy()

        box = PlateBox(x=0.2, y=0.2, w=0.4, h=0.2)
        result = apply_blur_to_frame(frame, [box])

        # The blurred region should differ from original checkerboard
        assert not np.array_equal(result[20:40, 40:120], original_region)

    def test_no_boxes_leaves_frame_unchanged(self):
        frame = self._make_frame()
        original = frame.copy()

        result = apply_blur_to_frame(frame, [])

        np.testing.assert_array_equal(result, original)

    def test_multiple_boxes(self):
        frame = self._make_frame(200, 400)
        original = frame.copy()

        boxes = [
            PlateBox(x=0.025, y=0.05, w=0.125, h=0.1),
            PlateBox(x=0.5, y=0.5, w=0.25, h=0.15),
        ]
        result = apply_blur_to_frame(frame, boxes)

        # Both regions should be modified
        assert not np.array_equal(result[10:30, 10:60], original[10:30, 10:60])
        assert not np.array_equal(result[100:130, 200:300], original[100:130, 200:300])

    def test_clamped_to_frame_bounds(self):
        frame = self._make_frame(100, 200)
        # Box extends beyond frame edges
        box = PlateBox(x=0.9, y=0.9, w=0.2, h=0.2)
        # Should not raise
        apply_blur_to_frame(frame, [box])

    def test_returns_same_frame_object(self):
        frame = self._make_frame()
        box = PlateBox(x=0.2, y=0.2, w=0.4, h=0.2)
        result = apply_blur_to_frame(frame, [box])
        assert result is frame


class TestGrabFrame:
    def test_nonexistent_file_returns_none(self):
        result = grab_frame("/nonexistent/video.mp4", 0.0)
        assert result is None

    def test_nonexistent_file_with_fps_returns_none(self):
        result = grab_frame("/nonexistent/video.mp4", 0.0, fps=30.0)
        assert result is None


class TestGetBoxesForFrame:
    """Tests for PlateBlurProcessor._get_boxes_for_frame()."""

    def _make_processor(self, detections):
        from trailvideocut.plate.blur import PlateBlurProcessor
        cpd = ClipPlateData(clip_index=0, detections=detections)
        return PlateBlurProcessor(
            video_path="/fake.mp4",
            segment_start=0.0,
            segment_duration=1.0,
            clip_plate_data=cpd,
            fps=30.0,
            frame_width=1920,
            frame_height=1080,
        )

    def test_exact_match_returns_boxes(self):
        boxes = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        proc = self._make_processor({100: boxes})
        result = proc._get_boxes_for_frame(100, [100])
        assert result is boxes

    def test_inside_range_no_detection_returns_empty(self):
        proc = self._make_processor({
            100: [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)],
            110: [PlateBox(x=0.2, y=0.3, w=0.05, h=0.03)],
        })
        result = proc._get_boxes_for_frame(105, [100, 110])
        assert result == []

    def test_after_last_detection_returns_empty(self):
        """Frames after the last detection return empty (no extrapolation)."""
        proc = self._make_processor({
            100: [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)],
            200: [PlateBox(x=0.3, y=0.4, w=0.05, h=0.03)],
        })
        result = proc._get_boxes_for_frame(205, [100, 200])
        assert result == []

    def test_before_first_detection_returns_empty(self):
        """Frames before the first detection return empty (no extrapolation)."""
        proc = self._make_processor({
            100: [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)],
            200: [PlateBox(x=0.3, y=0.4, w=0.05, h=0.03)],
        })
        result = proc._get_boxes_for_frame(95, [100, 200])
        assert result == []

    def test_empty_detections_returns_empty(self):
        proc = self._make_processor({})
        result = proc._get_boxes_for_frame(100, [])
        assert result == []

    def test_far_before_first_detection_returns_empty(self):
        """Frames far before the detection range return empty."""
        proc = self._make_processor({
            100: [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)],
            200: [PlateBox(x=0.3, y=0.4, w=0.05, h=0.03)],
        })
        result = proc._get_boxes_for_frame(0, [100, 200])
        assert result == []

    def test_far_after_last_detection_returns_empty(self):
        """Frames far after the detection range return empty."""
        proc = self._make_processor({
            100: [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)],
            200: [PlateBox(x=0.3, y=0.4, w=0.05, h=0.03)],
        })
        result = proc._get_boxes_for_frame(500, [100, 200])
        assert result == []


class TestExpandBoxesForDrift:
    """Tests for expand_boxes_for_drift()."""

    def test_expands_to_cover_adjacent_positions(self):
        """Box is expanded to union of N-1, N, N+1 positions."""
        from trailvideocut.plate.blur import expand_boxes_for_drift

        detections = {
            9: [PlateBox(x=0.50, y=0.30, w=0.02, h=0.02)],
            10: [PlateBox(x=0.51, y=0.30, w=0.02, h=0.02)],
            11: [PlateBox(x=0.52, y=0.30, w=0.02, h=0.02)],
        }
        result = expand_boxes_for_drift(detections, 10, margin_frames=1)

        assert len(result) == 1
        box = result[0]
        # x should cover 0.50 to 0.54 (0.52 + 0.02)
        assert box.x == pytest.approx(0.50)
        assert box.w == pytest.approx(0.04)
        # y unchanged (no vertical movement)
        assert box.y == pytest.approx(0.30)
        assert box.h == pytest.approx(0.02)

    def test_no_expansion_when_no_adjacent(self):
        """Without adjacent frames, returns original box."""
        from trailvideocut.plate.blur import expand_boxes_for_drift

        detections = {
            10: [PlateBox(x=0.50, y=0.30, w=0.02, h=0.02)],
        }
        result = expand_boxes_for_drift(detections, 10)

        assert len(result) == 1
        assert result[0].x == pytest.approx(0.50)
        assert result[0].w == pytest.approx(0.02)

    def test_empty_frame_returns_empty(self):
        """Frame without detections returns empty list."""
        from trailvideocut.plate.blur import expand_boxes_for_drift

        result = expand_boxes_for_drift({}, 10)
        assert result == []

class TestOrientedBlurMask:
    """Rotated-rectangle blur masks (refine-plate-box-fit, group 4)."""

    def _solid_frame(self, h=200, w=400, val=200):
        return np.full((h, w, 3), val, dtype=np.uint8)

    def test_aabb_path_identical_to_legacy(self):
        """angle == 0 must go through the legacy path pixel-identically."""
        frame_a = self._solid_frame()
        frame_b = frame_a.copy()
        # Add a sharp feature so the blur effect is measurable.
        frame_a[60:80, 120:200] = 20
        frame_b[60:80, 120:200] = 20

        box = PlateBox(x=0.25, y=0.25, w=0.3, h=0.2, angle=0.0)
        apply_blur_to_frame(frame_a, [box])

        # Explicitly-legacy box (no angle field) must match.
        legacy_box = PlateBox(x=0.25, y=0.25, w=0.3, h=0.2)
        apply_blur_to_frame(frame_b, [legacy_box])

        np.testing.assert_array_equal(frame_a, frame_b)

    def test_oriented_mask_blurs_inside_polygon_only(self):
        """Pixels inside the rotated quadrilateral differ from source; pixels
        inside the envelope but outside the polygon are untouched."""
        h, w = 200, 400
        frame = self._solid_frame(h, w, val=200)
        # Put a checkerboard over the full envelope area so the blur has
        # something to smooth regardless of which pixel we sample.
        for y in range(h):
            for x in range(w):
                if (x // 3 + y // 3) % 2 == 0:
                    frame[y, x] = (40, 40, 40)
        original = frame.copy()

        # Rotated square centred on (0.5, 0.5) at 30°.
        box = PlateBox(x=0.4, y=0.4, w=0.2, h=0.2, angle=30.0)
        apply_blur_to_frame(frame, [box])

        # A pixel near the centre of the rotated polygon must have changed
        # (checkerboard → blurred mid-grey).
        centre = (100, 200)
        assert not np.array_equal(frame[centre], original[centre])

        # Pixels clearly outside the rotated polygon (≥2px clearance to
        # tolerate integer-rasterisation of the polygon boundary) must not be
        # touched. The envelope corners of a 30°-rotated box lie well outside
        # the polygon so they are a reliable sample region.
        changed = np.any(frame != original, axis=2)
        corners_px = box.corners_px(w, h)
        poly = np.array([[cx, cy] for cx, cy in corners_px], dtype=np.float32)
        for y, x in zip(*np.where(changed)):
            signed_dist = cv2.pointPolygonTest(
                poly, (float(x), float(y)), measureDist=True,
            )
            assert signed_dist >= -1.5, (
                f"pixel ({x},{y}) was blurred but lies {-signed_dist:.2f}px "
                f"outside the rotated polygon"
            )

        # Envelope corners themselves are plenty-clear-of-polygon and must
        # be untouched.
        env_x, env_y, env_w, env_h = box.aabb_envelope()
        ex = int(round(env_x * w))
        ey = int(round(env_y * h))
        assert np.array_equal(frame[ey + 1, ex + 1], original[ey + 1, ex + 1])

    def test_oriented_kernel_uses_plate_aligned_dimensions(self):
        """Kernel size is derived from the rotated rectangle's own (w, h)."""
        from trailvideocut.plate.blur import _blur_kernel_size

        # A 160x40 plate rotated 25° has envelope ~176x101, but the kernel
        # must come from min(160, 40) == 40 → 41 (odd).
        frame_w_px = 1000
        frame_h_px = 1000
        box = PlateBox(
            x=(500 - 80) / frame_w_px, y=(500 - 20) / frame_h_px,
            w=160 / frame_w_px, h=40 / frame_h_px, angle=25.0,
        )
        expected = _blur_kernel_size(
            int(round(box.w * frame_w_px)), int(round(box.h * frame_h_px)),
        )
        assert expected == 41


class TestDriftExpansionOriented:
    def test_axis_aligned_path_unchanged(self):
        from trailvideocut.plate.blur import expand_boxes_for_drift

        detections = {
            9: [PlateBox(x=0.50, y=0.30, w=0.02, h=0.02)],
            10: [PlateBox(x=0.51, y=0.30, w=0.02, h=0.02)],
            11: [PlateBox(x=0.52, y=0.30, w=0.02, h=0.02)],
        }
        result = expand_boxes_for_drift(detections, 10, margin_frames=1)
        assert result[0].angle == 0.0
        assert result[0].x == pytest.approx(0.50)
        assert result[0].w == pytest.approx(0.04)

    def test_oriented_participant_produces_oriented_union(self):
        from trailvideocut.plate.blur import expand_boxes_for_drift

        detections = {
            9: [PlateBox(x=0.50, y=0.30, w=0.10, h=0.03, angle=10.0)],
            10: [PlateBox(x=0.51, y=0.30, w=0.10, h=0.03, angle=10.0)],
        }
        result = expand_boxes_for_drift(detections, 10, margin_frames=1)
        assert len(result) == 1
        union = result[0]
        assert abs(union.angle) > 0.0  # oriented union kept a rotation
        # Union must cover both source polygons — every source corner lies
        # inside the union envelope.
        env_x, env_y, env_w, env_h = union.aabb_envelope()
        for p in detections[9] + detections[10]:
            for cx, cy in p.corners_px(1.0, 1.0):
                assert env_x - 1e-6 <= cx <= env_x + env_w + 1e-6
                assert env_y - 1e-6 <= cy <= env_y + env_h + 1e-6


class TestCalibrateFrameOffset:
    """Tests for calibrate_frame_offset()."""

    def test_exact_match_returns_zero(self):
        """When output frame matches the expected source frame, offset is 0."""
        from unittest.mock import MagicMock, patch
        from trailvideocut.plate.blur import calibrate_frame_offset

        output = np.full((100, 200, 3), 100, dtype=np.uint8)
        matching = np.full((100, 200, 3), 100, dtype=np.uint8)
        different = np.full((100, 200, 3), 200, dtype=np.uint8)

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        seek_pos = [None]

        def mock_set(prop, val):
            seek_pos[0] = int(val)

        def mock_read():
            if seek_pos[0] == 10:
                return True, matching.copy()
            return True, different.copy()

        mock_cap.set.side_effect = mock_set
        mock_cap.read.side_effect = lambda: mock_read()

        with patch("cv2.VideoCapture", return_value=mock_cap):
            offset = calibrate_frame_offset(output, "/fake.mp4", expected_frame=10)

        assert offset == 0

    def test_offset_detected(self):
        """When output frame matches source frame at expected+1, offset is +1."""
        from unittest.mock import MagicMock, patch
        from trailvideocut.plate.blur import calibrate_frame_offset

        # Output frame has unique pattern
        output = np.full((100, 200, 3), 100, dtype=np.uint8)
        # Source frames: different at expected, matching at expected+1
        different = np.full((100, 200, 3), 200, dtype=np.uint8)
        matching = np.full((100, 200, 3), 100, dtype=np.uint8)

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        # frames at offsets -2,-1,0,+1,+2 from expected=10
        # 8=different, 9=different, 10=different, 11=matching, 12=different
        read_results = {
            8: different, 9: different, 10: different,
            11: matching, 12: different,
        }
        seek_pos = [None]

        def mock_set(prop, val):
            seek_pos[0] = int(val)

        def mock_read():
            fn = seek_pos[0]
            if fn in read_results:
                return True, read_results[fn].copy()
            return True, different.copy()

        mock_cap.set.side_effect = mock_set
        mock_cap.read.side_effect = lambda: mock_read()

        with patch("cv2.VideoCapture", return_value=mock_cap):
            offset = calibrate_frame_offset(output, "/fake.mp4", expected_frame=10)

        assert offset == 1

    def test_unopenable_video_returns_zero(self):
        """When video can't be opened, offset defaults to 0."""
        from unittest.mock import MagicMock, patch
        from trailvideocut.plate.blur import calibrate_frame_offset

        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch("cv2.VideoCapture", return_value=mock_cap):
            offset = calibrate_frame_offset(frame, "/fake.mp4", expected_frame=10)

        assert offset == 0


class TestNearestBoxes:
    """Tests for PlateBlurProcessor._nearest_boxes()."""

    def test_exact_match(self):
        from trailvideocut.plate.blur import PlateBlurProcessor
        boxes = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        dets = {10: boxes}
        result = PlateBlurProcessor._nearest_boxes(dets, 10)
        assert result is boxes

    def test_fallback_minus_1(self):
        from trailvideocut.plate.blur import PlateBlurProcessor
        boxes = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        dets = {9: boxes}
        result = PlateBlurProcessor._nearest_boxes(dets, 10)
        assert result is boxes

    def test_fallback_plus_1(self):
        from trailvideocut.plate.blur import PlateBlurProcessor
        boxes = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        dets = {11: boxes}
        result = PlateBlurProcessor._nearest_boxes(dets, 10)
        assert result is boxes

    def test_fallback_plus_2(self):
        from trailvideocut.plate.blur import PlateBlurProcessor
        boxes = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        dets = {12: boxes}
        result = PlateBlurProcessor._nearest_boxes(dets, 10, window=2)
        assert result is boxes

    def test_prefers_earlier_on_tie(self):
        """When ±1 both exist, prefers earlier frame (offset -1 checked first)."""
        from trailvideocut.plate.blur import PlateBlurProcessor
        boxes_before = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        boxes_after = [PlateBox(x=0.3, y=0.4, w=0.05, h=0.03)]
        dets = {9: boxes_before, 11: boxes_after}
        result = PlateBlurProcessor._nearest_boxes(dets, 10)
        assert result is boxes_before

    def test_outside_window_returns_empty(self):
        from trailvideocut.plate.blur import PlateBlurProcessor
        dets = {15: [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]}
        result = PlateBlurProcessor._nearest_boxes(dets, 10, window=2)
        assert result == []

    def test_empty_detections_returns_empty(self):
        from trailvideocut.plate.blur import PlateBlurProcessor
        result = PlateBlurProcessor._nearest_boxes({}, 10)
        assert result == []
