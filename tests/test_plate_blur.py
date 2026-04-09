"""Tests for plate blur processing."""

import numpy as np
import pytest

from trailvideocut.plate.blur import (
    _blur_kernel_size,
    apply_blur_to_frame,
    grab_frame,
)
from trailvideocut.plate.models import ClipPlateData, PlateBox


class TestBlurKernelSize:
    def test_full_strength_uses_min_dimension(self):
        k = _blur_kernel_size(1.0, 100, 40)
        # min(100,40)=40, max(3,40)=40, even->41
        assert k == 41

    def test_half_strength(self):
        k = _blur_kernel_size(0.5, 100, 40)
        # 0.5*40=20, max(3,20)=20, even->21
        assert k == 21

    def test_zero_strength_returns_zero(self):
        assert _blur_kernel_size(0.0, 100, 40) == 0

    def test_negative_strength_returns_zero(self):
        assert _blur_kernel_size(-0.5, 100, 40) == 0

    def test_tiny_plate_minimum_kernel(self):
        k = _blur_kernel_size(0.01, 10, 5)
        # 0.01*5=0, max(3,0)=3
        assert k == 3

    def test_result_always_odd(self):
        for strength in [0.1, 0.25, 0.5, 0.75, 1.0]:
            k = _blur_kernel_size(strength, 80, 60)
            if k > 0:
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

        box = PlateBox(x=0.2, y=0.2, w=0.4, h=0.2, blur_strength=1.0)
        result = apply_blur_to_frame(frame, [box])

        # The blurred region should differ from original checkerboard
        assert not np.array_equal(result[20:40, 40:120], original_region)

    def test_zero_strength_leaves_frame_unchanged(self):
        frame = self._make_frame()
        original = frame.copy()

        box = PlateBox(x=0.2, y=0.2, w=0.4, h=0.2, blur_strength=0.0)
        result = apply_blur_to_frame(frame, [box])

        np.testing.assert_array_equal(result, original)

    def test_no_boxes_leaves_frame_unchanged(self):
        frame = self._make_frame()
        original = frame.copy()

        result = apply_blur_to_frame(frame, [])

        np.testing.assert_array_equal(result, original)

    def test_multiple_boxes(self):
        frame = self._make_frame(200, 400)
        original = frame.copy()

        boxes = [
            PlateBox(x=0.025, y=0.05, w=0.125, h=0.1, blur_strength=1.0),
            PlateBox(x=0.5, y=0.5, w=0.25, h=0.15, blur_strength=0.5),
        ]
        result = apply_blur_to_frame(frame, boxes)

        # Both regions should be modified
        assert not np.array_equal(result[10:30, 10:60], original[10:30, 10:60])
        assert not np.array_equal(result[100:130, 200:300], original[100:130, 200:300])

    def test_clamped_to_frame_bounds(self):
        frame = self._make_frame(100, 200)
        # Box extends beyond frame edges
        box = PlateBox(x=0.9, y=0.9, w=0.2, h=0.2, blur_strength=1.0)
        # Should not raise
        apply_blur_to_frame(frame, [box])

    def test_returns_same_frame_object(self):
        frame = self._make_frame()
        box = PlateBox(x=0.2, y=0.2, w=0.4, h=0.2, blur_strength=1.0)
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

    def test_after_last_detection_returns_nearest(self):
        boxes_last = [PlateBox(x=0.3, y=0.4, w=0.05, h=0.03)]
        proc = self._make_processor({
            100: [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)],
            200: boxes_last,
        })
        result = proc._get_boxes_for_frame(205, [100, 200])
        assert result is boxes_last

    def test_before_first_detection_returns_nearest(self):
        boxes_first = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        proc = self._make_processor({
            100: boxes_first,
            200: [PlateBox(x=0.3, y=0.4, w=0.05, h=0.03)],
        })
        result = proc._get_boxes_for_frame(95, [100, 200])
        assert result is boxes_first

    def test_empty_detections_returns_empty(self):
        proc = self._make_processor({})
        result = proc._get_boxes_for_frame(100, [])
        assert result == []

    def test_manual_plate_beyond_clip_used_for_extrapolation(self):
        """User-added manual plates beyond auto-detection range are respected."""
        auto_boxes = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        manual_boxes = [PlateBox(x=0.5, y=0.6, w=0.08, h=0.04, manual=True)]
        proc = self._make_processor({
            100: auto_boxes,
            200: auto_boxes,
            # Manual plate added at frame 210 (beyond auto range)
            210: manual_boxes,
        })
        det_keys = [100, 200, 210]
        # Frame 212 is beyond range, nearest is 210 (manual)
        result = proc._get_boxes_for_frame(212, det_keys)
        assert result is manual_boxes

    def test_nearest_key_picks_closer_when_between_boundaries(self):
        """When frame is outside range, pick the closer boundary."""
        boxes_a = [PlateBox(x=0.1, y=0.2, w=0.05, h=0.03)]
        boxes_b = [PlateBox(x=0.5, y=0.6, w=0.08, h=0.04)]
        proc = self._make_processor({50: boxes_a, 100: boxes_b})
        # Frame 45 is before range, nearest is 50
        result = proc._get_boxes_for_frame(45, [50, 100])
        assert result is boxes_a


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

    def test_preserves_blur_strength(self):
        """Expanded box keeps the original blur_strength."""
        from trailvideocut.plate.blur import expand_boxes_for_drift

        detections = {
            10: [PlateBox(x=0.50, y=0.30, w=0.02, h=0.02, blur_strength=0.7)],
            11: [PlateBox(x=0.52, y=0.30, w=0.02, h=0.02)],
        }
        result = expand_boxes_for_drift(detections, 10)
        assert result[0].blur_strength == 0.7


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
