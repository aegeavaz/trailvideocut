"""Tests for the plate detection module."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.plate.detector import PlateDetector, _iou


class TestPlateBox:
    def test_defaults(self):
        box = PlateBox(x=0.1, y=0.2, w=0.3, h=0.1)
        assert box.confidence == 0.0
        assert box.manual is False

    def test_manual_flag(self):
        box = PlateBox(x=0.1, y=0.2, w=0.3, h=0.1, manual=True)
        assert box.manual is True


class TestClipPlateData:
    def test_empty(self):
        data = ClipPlateData(clip_index=0)
        assert data.detections == {}

    def test_with_detections(self):
        box = PlateBox(x=0.1, y=0.2, w=0.3, h=0.1, confidence=0.9)
        data = ClipPlateData(clip_index=2, detections={10: [box]})
        assert len(data.detections[10]) == 1
        assert data.detections[10][0].confidence == 0.9


class TestIOU:
    def test_no_overlap(self):
        a = PlateBox(x=0.0, y=0.0, w=0.1, h=0.1)
        b = PlateBox(x=0.5, y=0.5, w=0.1, h=0.1)
        assert _iou(a, b) == 0.0

    def test_full_overlap(self):
        a = PlateBox(x=0.1, y=0.1, w=0.2, h=0.2)
        assert _iou(a, a) == pytest.approx(1.0)

    def test_partial_overlap(self):
        a = PlateBox(x=0.0, y=0.0, w=0.2, h=0.2)
        b = PlateBox(x=0.1, y=0.1, w=0.2, h=0.2)
        # Overlap area: 0.1 * 0.1 = 0.01
        # Union: 0.04 + 0.04 - 0.01 = 0.07
        assert _iou(a, b) == pytest.approx(0.01 / 0.07, rel=1e-3)


class TestPlateDetectorParseOutput:
    """Test output parsing without needing a real model."""

    def _make_detector_with_mock_net(self, threshold=0.5):
        # Force cv2.dnn backend by mocking other backends away
        with patch("trailvideocut.plate.detector._BACKEND", "cv2"), \
             patch("cv2.dnn.readNetFromONNX") as mock_read:
            mock_net = MagicMock()
            mock_read.return_value = mock_net
            det = PlateDetector("fake.onnx", confidence_threshold=threshold)
        return det

    def test_parse_high_confidence(self):
        det = self._make_detector_with_mock_net(threshold=0.5)
        # YOLOv8 shape: (1, 5, N) where 5 = cx,cy,w,h,conf and N > 5.
        # Use N=8 detections, first has high conf, rest are zeros (below threshold).
        # Detection: cx=320, cy=320, w=100, h=50, conf=0.9
        data = np.zeros((1, 5, 8), dtype=np.float32)
        data[0, 0, 0] = 320  # cx
        data[0, 1, 0] = 320  # cy
        data[0, 2, 0] = 100  # w
        data[0, 3, 0] = 50   # h
        data[0, 4, 0] = 0.9  # conf
        boxes = det._parse_output(data, img_w=640, img_h=640)
        assert len(boxes) == 1
        assert boxes[0].confidence == pytest.approx(0.9)

    def test_parse_low_confidence_filtered(self):
        det = self._make_detector_with_mock_net(threshold=0.5)
        data = np.zeros((1, 5, 8), dtype=np.float32)
        data[0, 0, 0] = 320
        data[0, 1, 0] = 320
        data[0, 2, 0] = 100
        data[0, 3, 0] = 50
        data[0, 4, 0] = 0.3  # below threshold
        boxes = det._parse_output(data, img_w=640, img_h=640)
        assert len(boxes) == 0

    def test_parse_empty_detections(self):
        det = self._make_detector_with_mock_net()
        output = np.zeros((1, 5, 0), dtype=np.float32)
        boxes = det._parse_output(output, img_w=640, img_h=640)
        assert boxes == []


class TestPlateDetectorCancellation:
    def test_cancellation_returns_partial(self):
        """detect_clip should return partial results when cancelled."""
        with patch("trailvideocut.plate.detector._BACKEND", "cv2"), \
             patch("cv2.dnn.readNetFromONNX"):
            det = PlateDetector("fake.onnx")

        frame_count = 0

        def mock_cancelled():
            return frame_count >= 5

        with patch("cv2.VideoCapture") as mock_cap_cls, \
             patch("trailvideocut.gpu._find_ffmpeg", return_value=None):
            mock_cap = MagicMock()
            mock_cap_cls.return_value = mock_cap
            mock_cap.get.return_value = 10.0  # 10 fps
            # Return fake frames
            mock_cap.read.return_value = (True, np.zeros((100, 100, 3), dtype=np.uint8))

            # Mock detect_frame to track calls
            call_count = [0]

            def counting_detect(frame):
                nonlocal frame_count
                call_count[0] += 1
                frame_count = call_count[0]
                return []

            det.detect_frame = counting_detect
            det.detect_frame_tiled = counting_detect

            result = det.detect_clip(
                "fake.mp4", 0.0, 2.0, clip_index=0,
                cancelled=mock_cancelled,
            )

            assert isinstance(result, ClipPlateData)
            # Should have stopped early (5 frames, not 20)
            assert call_count[0] == 5
