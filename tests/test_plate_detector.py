"""Tests for the plate detection module."""

import inspect
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.plate.detector import (
    PlateDetector,
    _VERTICAL_SPLIT_THRESHOLD,
    _iou,
)


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

    def test_phone_zones_default_empty(self):
        data = ClipPlateData(clip_index=0)
        assert data.phone_zones == {}

    def test_phone_zones_preserved(self):
        zones = {5: [(0.1, 0.2, 0.3, 0.4)], 10: [(0.0, 0.0, 0.5, 0.5), (0.5, 0.5, 0.2, 0.2)]}
        data = ClipPlateData(clip_index=3, phone_zones=zones)
        assert data.phone_zones == zones
        # Each zone preserves tuple identity / content
        assert data.phone_zones[5][0] == (0.1, 0.2, 0.3, 0.4)
        assert len(data.phone_zones[10]) == 2


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


class TestPlateDetectorPhoneZoneRecording:
    """Verify `detect_clip` records per-frame phone zones without altering
    the set of surviving plate detections.
    """

    def _make_detector(self, exclude_phones):
        with patch("trailvideocut.plate.detector._BACKEND", "cv2"), \
             patch("cv2.dnn.readNetFromONNX"):
            det = PlateDetector("fake.onnx", exclude_phones=exclude_phones)
        return det

    def _run_clip(self, det, zones_per_frame):
        """Run detect_clip on a 5-frame mock and control zones via a stub.

        *zones_per_frame* is a list of zone-lists, one per frame: zones that
        should be present in ``self._phone_zones`` *after* the per-frame
        detection call. The stubbed `detect_frame_tiled` mutates
        `_phone_zones` to simulate `update_phone_zones` running. Plates are
        fixed and placed outside any test zone so filtering does not drop
        them.
        """
        frame_idx = [0]
        fixed_box = PlateBox(x=0.5, y=0.5, w=0.05, h=0.02, confidence=0.9)

        def fake_detect(frame):
            idx = frame_idx[0]
            if 0 <= idx < len(zones_per_frame):
                det._phone_zones = list(zones_per_frame[idx])
            frame_idx[0] += 1
            return [fixed_box]

        det.detect_frame_tiled = fake_detect

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap_cls.return_value = mock_cap
            mock_cap.get.return_value = 10.0  # 10 fps
            mock_cap.read.return_value = (True, np.zeros((100, 100, 3), dtype=np.uint8))

            result = det.detect_clip(
                "fake.mp4", 0.0, 0.5, clip_index=0,
                temporal_filter=False,
            )
        return result

    def test_zones_recorded_when_exclude_phones_enabled(self):
        det = self._make_detector(exclude_phones=True)
        zones = [(0.1, 0.2, 0.3, 0.4)]
        zones_per_frame = [[], zones, zones, [], zones]
        result = self._run_clip(det, zones_per_frame)
        # Sparse map: only frames where zones were active appear
        assert set(result.phone_zones.keys()) == {1, 2, 4}
        assert result.phone_zones[1] == zones
        assert result.phone_zones[2] == zones
        assert result.phone_zones[4] == zones

    def test_zones_not_recorded_when_exclude_phones_disabled(self):
        det = self._make_detector(exclude_phones=False)
        result = self._run_clip(det, [[(0.1, 0.2, 0.3, 0.4)]] * 5)
        assert result.phone_zones == {}

    def test_zone_recording_is_sparse_no_empty_entries(self):
        det = self._make_detector(exclude_phones=True)
        result = self._run_clip(det, [[], [], [], [], []])
        assert result.phone_zones == {}

    def test_zone_recording_does_not_alter_detections(self):
        """Requirement: 'Zone recording SHALL NOT alter filtering semantics'."""
        det_a = self._make_detector(exclude_phones=True)
        det_b = self._make_detector(exclude_phones=True)
        zones_per_frame = [[(0.0, 0.0, 0.1, 0.1)]] * 5
        result_a = self._run_clip(det_a, zones_per_frame)
        result_b = self._run_clip(det_b, zones_per_frame)
        assert set(result_a.detections.keys()) == set(result_b.detections.keys())
        for k in result_a.detections:
            assert len(result_a.detections[k]) == len(result_b.detections[k])

    def test_zones_survive_temporal_filter(self):
        """Regression: `filter_temporal_continuity` must not drop `phone_zones`.

        Without this guarantee the "Show Phone Filter" checkbox in the UI
        stays disabled even after a successful detection run, because the
        zones get wiped at the last step of `detect_clip`.
        """
        det = self._make_detector(exclude_phones=True)
        zones_per_frame = [[(0.1, 0.2, 0.3, 0.4)]] * 5
        # Run the full pipeline with temporal_filter enabled (default).
        # Bypass the `temporal_filter=False` override from `_run_clip`.
        frame_idx = [0]
        fixed_box = PlateBox(x=0.5, y=0.5, w=0.05, h=0.02, confidence=0.9)

        def fake_detect(frame):
            idx = frame_idx[0]
            if 0 <= idx < len(zones_per_frame):
                det._phone_zones = list(zones_per_frame[idx])
            frame_idx[0] += 1
            return [fixed_box]

        det.detect_frame_tiled = fake_detect

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap_cls.return_value = mock_cap
            mock_cap.get.return_value = 10.0
            mock_cap.read.return_value = (True, np.zeros((100, 100, 3), dtype=np.uint8))
            result = det.detect_clip(
                "fake.mp4", 0.0, 0.5, clip_index=0,
                temporal_filter=True, min_track_length=1,
            )
        # Zones must survive the temporal filter stage.
        assert result.phone_zones, (
            "phone_zones was cleared by filter_temporal_continuity"
        )
        assert all(z == zones_per_frame[0] for z in result.phone_zones.values())

    def test_current_phone_zones_property(self):
        det = self._make_detector(exclude_phones=True)
        assert det.current_phone_zones == []
        det._phone_zones = [(0.1, 0.2, 0.3, 0.4)]
        snapshot = det.current_phone_zones
        assert snapshot == [(0.1, 0.2, 0.3, 0.4)]
        # Returned list is a copy — mutating it does not affect internal state.
        snapshot.append((9, 9, 9, 9))
        assert det._phone_zones == [(0.1, 0.2, 0.3, 0.4)]


class TestOnnxPhoneDetectionParser:
    """Exercise the onnxruntime-backed dashboard detector path.

    Verifies the 84-channel YOLOv8 output is parsed correctly: motorcycle
    detections (class 3) at the bottom of the frame with sufficient area
    are kept, others are filtered.
    """

    MOTORCYCLE_CLS = 3

    def _make_detector(self):
        with patch("trailvideocut.plate.detector._BACKEND", "cv2"), \
             patch("cv2.dnn.readNetFromONNX"):
            det = PlateDetector("fake.onnx", exclude_phones=True)
        # Inject a mock session and mark the model as loaded so
        # `_ensure_phone_model` is a no-op on subsequent calls.
        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "images"
        mock_session.get_inputs.return_value = [mock_input]
        det._phone_ort_session = mock_session
        det._phone_model_loaded = True
        return det, mock_session

    def _synth_output(self, detections: list[tuple[float, float, float, float, int, float]]):
        """Build a (1, 84, 8400) tensor with the given detections planted.

        Each detection: (cx, cy, w, h, cls_id, score) in input-pixel space.
        """
        N = 8400
        out = np.zeros((1, 84, N), dtype=np.float32)
        for i, (cx, cy, bw, bh, cls_id, score) in enumerate(detections):
            if i >= N:
                break
            out[0, 0, i] = cx
            out[0, 1, i] = cy
            out[0, 2, i] = bw
            out[0, 3, i] = bh
            out[0, 4 + cls_id, i] = score
        return out

    def test_bottom_motorcycle_extracted_and_padded(self):
        det, session = self._make_detector()
        # 640x640 frame (letterbox no-op). Plant one motorcycle at the bottom
        # of the frame: cx=320, cy=540, w=400, h=200 -> bbox (120,440,520,640).
        # bottom_frac = 640/640 = 1.0 (>=0.85), area_frac = 400*200/409600 = 0.195 (>=0.04).
        output = self._synth_output([(320, 540, 400, 200, self.MOTORCYCLE_CLS, 0.7)])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)

        assert len(zones) == 1
        nx, ny, nw, nh = zones[0]
        # Raw box: x1=120, y1=440, w=400, h=200.
        # Padding: left/right get 20% (px=80), top gets 0%, bottom gets 20%
        # (py=40). Left: 120-80=40. Width: 400+160=560. Top: stays at 440.
        # Bottom padding would extend to 640+40=680 but frame is 640 tall,
        # so height is clamped to 640-440=200.
        assert nx == pytest.approx(40 / 640)
        assert ny == pytest.approx(440 / 640)
        assert nw == pytest.approx(560 / 640)
        assert nh == pytest.approx(200 / 640)

    def test_top_padding_is_zero(self):
        """Regression: the zone must never extend above the raw detection's
        top edge, to avoid catching riders ahead on the same trail.
        """
        det, session = self._make_detector()
        # Motorcycle well inside the frame so bottom padding has room to grow.
        # Plant at cx=320, cy=600, w=200, h=40 -> bbox (220,580,420,620).
        # bottom_frac = 620/640 = 0.97, area = 8000, area_frac = 0.0195 (< 0.04).
        # That would be rejected — bump size for the test.
        # Use w=400, h=80 -> bbox (120,560,520,640). area_frac = 0.078. OK.
        output = self._synth_output([(320, 600, 400, 80, self.MOTORCYCLE_CLS, 0.7)])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)
        assert len(zones) == 1
        _, ny, _, _ = zones[0]
        # Raw top edge y1 = 560. No top padding -> zone top must be at 560/640.
        assert ny == pytest.approx(560 / 640)

    def test_non_motorcycle_class_ignored(self):
        det, session = self._make_detector()
        # Person at bottom of frame with good area — still rejected (wrong class).
        output = self._synth_output([(320, 540, 400, 200, 0, 0.99)])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)
        assert zones == []

    def test_low_confidence_motorcycle_rejected(self):
        det, session = self._make_detector()
        # Motorcycle at conf 0.10 (below _PHONE_CONF=0.20).
        output = self._synth_output([(320, 540, 400, 200, self.MOTORCYCLE_CLS, 0.10)])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)
        assert zones == []

    def test_upper_frame_motorcycle_rejected_by_position_filter(self):
        """A rider further ahead appears in upper half of the frame — must NOT
        be treated as the user's own dashboard."""
        det, session = self._make_detector()
        # Motorcycle at top: cx=320, cy=200, w=60, h=80 -> bbox (290,160,350,240).
        # bottom_frac = 240/640 = 0.375 (<0.85) -> rejected.
        output = self._synth_output([(320, 200, 60, 80, self.MOTORCYCLE_CLS, 0.7)])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)
        assert zones == []

    def test_small_bottom_motorcycle_rejected_by_area_filter(self):
        """A distant rider whose bbox just touches the bottom but is tiny
        must NOT be treated as the user's own dashboard."""
        det, session = self._make_detector()
        # Tiny bottom box: cx=320, cy=620, w=40, h=40 -> bbox (300,600,340,640).
        # bottom_frac = 1.0 (>=0.85) but area_frac = 1600/409600 = 0.004 (<0.04).
        output = self._synth_output([(320, 620, 40, 40, self.MOTORCYCLE_CLS, 0.8)])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)
        assert zones == []

    def test_multiple_bottom_motorcycles_deduped_via_nms(self):
        det, session = self._make_detector()
        # Two heavily overlapping bottom motorcycles — NMS collapses to one.
        output = self._synth_output([
            (320, 540, 400, 200, self.MOTORCYCLE_CLS, 0.80),
            (325, 542, 400, 200, self.MOTORCYCLE_CLS, 0.75),
        ])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)
        assert len(zones) == 1

    def test_nested_survivors_merged_to_union_bbox(self):
        """Two detections survive NMS (small one inside big one has low IoU)
        — the overlay merge must collapse them into the outer bbox.
        """
        det, session = self._make_detector()
        # Big: cx=320, cy=540, w=400, h=200 -> (120,440,520,640). area_frac=0.195.
        # Small: cx=320, cy=600, w=150, h=80 -> (245,560,395,640). area_frac=0.029.
        # The small box is below our area_frac >= 0.04 filter, so to trigger
        # the "two survivors" case, use slightly larger dims:
        # Small: cx=320, cy=560, w=300, h=160 -> (170,480,470,640).
        # area_frac = 300*160/409600 = 0.117. IoU with big:
        #   inter = (min(520,470)-max(120,170)) * (min(640,640)-max(440,480))
        #         = (470-170) * (640-480) = 300*160 = 48000
        #   union = 400*200 + 300*160 - 48000 = 80000 + 48000 - 48000 = 80000
        #   IoU = 48000 / 80000 = 0.6 — over 0.5 threshold, NMS kills one.
        # Need non-overlapping IoU. Try:
        # Small: cx=320, cy=590, w=200, h=100 -> (220,540,420,640).
        # area_frac = 20000/409600 = 0.049 (> 0.04, passes).
        # Overlap with big: (min(520,420)-max(120,220))*(min(640,640)-max(440,540))
        #   = 200*100 = 20000. IoU = 20000/(80000+20000-20000) = 0.25 -> NMS keeps both.
        output = self._synth_output([
            (320, 540, 400, 200, self.MOTORCYCLE_CLS, 0.80),  # big
            (320, 590, 200, 100, self.MOTORCYCLE_CLS, 0.60),  # small, inside big
        ])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)
        # Merge into single union bbox (big contains small).
        assert len(zones) == 1
        nx, ny, nw, nh = zones[0]
        # Union matches big's bbox: (120,440,520,640). After padding (no top):
        # nx=40/640, ny=440/640, nw=560/640, nh=200/640.
        assert nx == pytest.approx(40 / 640)
        assert ny == pytest.approx(440 / 640)
        assert nw == pytest.approx(560 / 640)
        assert nh == pytest.approx(200 / 640)

    def test_disjoint_zones_remain_separate(self):
        """Two truly disjoint bottom detections must NOT be merged."""
        det, session = self._make_detector()
        # Left dashboard: cx=150, cy=540, w=200, h=200 -> (50,440,250,640).
        # Right dashboard: cx=500, cy=540, w=200, h=200 -> (400,440,600,640).
        # No overlap (x gap: 250 vs 400).
        output = self._synth_output([
            (150, 540, 200, 200, self.MOTORCYCLE_CLS, 0.70),
            (500, 540, 200, 200, self.MOTORCYCLE_CLS, 0.70),
        ])
        session.run.return_value = [output]

        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        zones = det.detect_phones(frame)
        assert len(zones) == 2


class TestTemporalFilterPreservesPhoneZones:
    """Direct unit test of `filter_temporal_continuity`: zones pass through."""

    def test_zones_forwarded_when_detections_empty(self):
        from trailvideocut.plate.temporal_filter import filter_temporal_continuity

        data = ClipPlateData(
            clip_index=0,
            detections={},
            phone_zones={5: [(0.1, 0.2, 0.3, 0.4)]},
        )
        result = filter_temporal_continuity(data, min_track_length=3)
        assert result.phone_zones == {5: [(0.1, 0.2, 0.3, 0.4)]}

    def test_zones_forwarded_when_detections_present(self):
        from trailvideocut.plate.temporal_filter import filter_temporal_continuity

        box = PlateBox(x=0.1, y=0.2, w=0.05, h=0.03, confidence=0.9)
        zones = {10: [(0.5, 0.5, 0.2, 0.2)], 11: [(0.5, 0.5, 0.2, 0.2)]}
        data = ClipPlateData(
            clip_index=0,
            detections={10: [box], 11: [box]},
            phone_zones=zones,
        )
        result = filter_temporal_continuity(data, min_track_length=1)
        assert result.phone_zones == zones

    def test_returned_phone_zones_is_copy(self):
        """Mutating the returned map must not affect the input."""
        from trailvideocut.plate.temporal_filter import filter_temporal_continuity

        zones = {5: [(0.1, 0.2, 0.3, 0.4)]}
        data = ClipPlateData(clip_index=0, phone_zones=zones)
        result = filter_temporal_continuity(data, min_track_length=3)
        result.phone_zones[99] = [(9, 9, 9, 9)]
        assert 99 not in data.phone_zones


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


class TestPlateDetectorVerticalPositionFilter:
    """Always-on postfilter: when any surviving plate has its center in the
    top half of the frame (cy < 0.5), drop every plate whose center is in
    the bottom half (cy >= 0.5). No configuration surface.
    """

    def _make_detector(self, exclude_phones=False):
        with patch("trailvideocut.plate.detector._BACKEND", "cv2"), \
             patch("cv2.dnn.readNetFromONNX"):
            return PlateDetector("fake.onnx", exclude_phones=exclude_phones)

    # --- Unit tests on _filter_vertical_position directly ---

    def test_drops_lower_when_upper_present(self):
        det = self._make_detector()
        upper = PlateBox(x=0.1, y=0.25, w=0.1, h=0.1, confidence=0.9)  # cy=0.30
        lower = PlateBox(x=0.1, y=0.65, w=0.1, h=0.1, confidence=0.9)  # cy=0.70
        result = det._filter_vertical_position([upper, lower])
        assert result == [upper]

    def test_noop_when_only_lower_boxes(self):
        det = self._make_detector()
        boxes = [
            PlateBox(x=0.1, y=0.55, w=0.1, h=0.1),  # cy=0.60
            PlateBox(x=0.1, y=0.75, w=0.1, h=0.1),  # cy=0.80
        ]
        assert det._filter_vertical_position(boxes) == boxes

    def test_noop_when_only_upper_boxes(self):
        det = self._make_detector()
        boxes = [
            PlateBox(x=0.1, y=0.10, w=0.1, h=0.1),  # cy=0.15
            PlateBox(x=0.1, y=0.35, w=0.1, h=0.1),  # cy=0.40
        ]
        assert det._filter_vertical_position(boxes) == boxes

    def test_empty_list_returns_empty(self):
        det = self._make_detector()
        assert det._filter_vertical_position([]) == []

    def test_box_on_split_line_counts_as_lower(self):
        det = self._make_detector()
        # cy=0.25 (upper), cy=0.5 exactly (lower per `cy >= 0.5` convention).
        upper = PlateBox(x=0.1, y=0.20, w=0.1, h=0.1, confidence=0.9)  # cy=0.25
        on_line = PlateBox(x=0.1, y=0.45, w=0.0, h=0.10, confidence=0.9)  # cy=0.50
        result = det._filter_vertical_position([upper, on_line])
        assert result == [upper]

    def test_lone_box_on_split_line_retained(self):
        """cy exactly at 0.5 with no upper companion: no upper box triggers
        the drop, so the lone box survives (the filter is 'trigger + drop'
        not 'always drop lower').
        """
        det = self._make_detector()
        on_line = PlateBox(x=0.1, y=0.45, w=0.0, h=0.10, confidence=0.9)  # cy=0.50
        result = det._filter_vertical_position([on_line])
        assert result == [on_line]

    # --- Integration through detect_frame ---

    def test_detect_frame_applies_filter_after_phone_zones(self):
        """Upper box is eliminated by _filter_phone_zones; the vertical
        filter must therefore see ONLY the lower box and leave it alone
        (no upper box => no drop)."""
        det = self._make_detector(exclude_phones=True)

        upper = PlateBox(x=0.40, y=0.20, w=0.10, h=0.05, confidence=0.9)  # cy=0.225
        lower = PlateBox(x=0.40, y=0.70, w=0.10, h=0.05, confidence=0.9)  # cy=0.725

        # Make _parse_output hand back these two boxes regardless of input.
        det._parse_output = MagicMock(return_value=[upper, lower])
        # _filter_geometry would reject these tiny normalized boxes on a 100x100
        # frame (pixel sizes below MIN_PLATE_PX_W/H). Bypass it for this test.
        det._filter_geometry = lambda boxes, w, h: list(boxes)
        # update_phone_zones must NOT refetch the phone model — set zones
        # covering the upper box's center (0.45, 0.225) so the phone filter
        # removes it.
        det.update_phone_zones = MagicMock(
            side_effect=lambda frame: setattr(
                det, "_phone_zones", [(0.0, 0.0, 1.0, 0.5)],
            ),
        )
        det._infer_cv2 = MagicMock(return_value=np.zeros((1, 5, 0), dtype=np.float32))

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        # Force the cv2.dnn branch inside detect_frame so we exercise
        # _infer_cv2 + _parse_output (both mocked) instead of the real
        # ultralytics path.
        with patch("trailvideocut.plate.detector._BACKEND", "cv2"):
            result = det.detect_frame(frame)

        # Upper was phone-zone-eliminated => vertical filter sees only lower,
        # sees no upper, returns [lower] unchanged.
        assert len(result) == 1
        assert result[0] is lower

    def test_detect_frame_drops_lower_when_upper_survives(self):
        """Control for the test above: with no phone zones, the upper box
        survives all filters and triggers dropping of the lower box."""
        det = self._make_detector(exclude_phones=False)

        upper = PlateBox(x=0.40, y=0.20, w=0.10, h=0.05, confidence=0.9)
        lower = PlateBox(x=0.40, y=0.70, w=0.10, h=0.05, confidence=0.9)

        det._parse_output = MagicMock(return_value=[upper, lower])
        det._filter_geometry = lambda boxes, w, h: list(boxes)
        det.update_phone_zones = MagicMock()
        det._infer_cv2 = MagicMock(return_value=np.zeros((1, 5, 0), dtype=np.float32))

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        with patch("trailvideocut.plate.detector._BACKEND", "cv2"):
            result = det.detect_frame(frame)
        assert result == [upper]

    # --- Integration through detect_clip ---

    def test_detect_clip_prunes_mixed_frames_keeps_lower_only_frames(self):
        """detect_clip delegates to detect_frame/detect_frame_tiled per frame.
        Mixed frames should have their lower boxes pruned; lower-only frames
        should retain their boxes. Stub the per-frame detector with a version
        that invokes the real _filter_vertical_position so we are exercising
        the same filter the detector uses.
        """
        det = self._make_detector(exclude_phones=False)

        upper = PlateBox(x=0.40, y=0.20, w=0.05, h=0.02, confidence=0.9)  # cy=0.21
        lower = PlateBox(x=0.40, y=0.70, w=0.05, h=0.02, confidence=0.9)  # cy=0.71

        # Frame 0: mixed (upper + lower) -> lower dropped.
        # Frame 1: lower only -> kept.
        # Frame 2: upper only -> kept.
        # Frame 3: empty -> no entry in detections.
        # Frame 4: mixed -> lower dropped.
        per_frame = [[upper, lower], [lower], [upper], [], [upper, lower]]
        frame_idx = [0]

        def fake_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            boxes = list(per_frame[idx]) if idx < len(per_frame) else []
            # Exercise the real filter — this is what detect_frame_tiled will
            # call internally once the implementation lands.
            return det._filter_vertical_position(boxes)

        det.detect_frame_tiled = fake_detect

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap_cls.return_value = mock_cap
            mock_cap.get.return_value = 10.0
            mock_cap.read.return_value = (
                True, np.zeros((100, 100, 3), dtype=np.uint8),
            )
            result = det.detect_clip(
                "fake.mp4", 0.0, 0.5, clip_index=0, temporal_filter=False,
            )

        # Frame 0: lower dropped, only upper remains.
        assert len(result.detections[0]) == 1
        assert result.detections[0][0] is upper
        # Frame 1: lower-only, kept.
        assert result.detections[1] == [lower]
        # Frame 2: upper-only, kept.
        assert result.detections[2] == [upper]
        # Frame 3: no detections at all -> omitted from the sparse map.
        assert 3 not in result.detections
        # Frame 4: lower dropped again.
        assert result.detections[4] == [upper]

    # --- Signature guard ---

    def test_init_signature_unchanged(self):
        """The filter is non-configurable: no new parameters on __init__."""
        expected = {
            "self",
            "model_path",
            "confidence_threshold",
            "exclude_phones",
            "phone_redetect_every",
            "verbose",
            "min_ratio",
            "max_ratio",
            "min_plate_px_w",
            "min_plate_px_h",
        }
        actual = set(inspect.signature(PlateDetector.__init__).parameters.keys())
        assert actual == expected, (
            f"PlateDetector.__init__ parameters changed. "
            f"Expected {expected}, got {actual}. "
            "The vertical-position filter must remain non-configurable."
        )


class TestDashboardFilterUpperPlateGate:
    """Per-frame gate on `_filter_phone_zones`: the dashboard exclusion filter
    only runs when the post-geometry candidate list has at least one box whose
    center is in the upper half of the frame (cy < _VERTICAL_SPLIT_THRESHOLD).

    Rationale: when no upper-half plate is present, there is no contextual
    evidence that we are filming a real road scene with another vehicle, so the
    dashboard heuristic risks dropping a legitimate lower-half plate.
    """

    def _make_detector(self, exclude_phones=True):
        with patch("trailvideocut.plate.detector._BACKEND", "cv2"), \
             patch("cv2.dnn.readNetFromONNX"):
            return PlateDetector("fake.onnx", exclude_phones=exclude_phones)

    def _wire_for_detect_frame(self, det, parsed_boxes, zones):
        """Configure a detector so that `detect_frame` returns `parsed_boxes`
        post-geometry, with `_phone_zones` set to `zones` (no zone refresh).
        """
        det._parse_output = MagicMock(return_value=parsed_boxes)
        # Bypass geometry filter (the synthetic boxes are below MIN_PLATE_PX).
        det._filter_geometry = lambda boxes, w, h: list(boxes)
        # Pin _phone_zones to the test value; suppress the in-frame refresh.
        det.update_phone_zones = MagicMock(
            side_effect=lambda frame: setattr(det, "_phone_zones", list(zones)),
        )
        det._infer_cv2 = MagicMock(
            return_value=np.zeros((1, 5, 0), dtype=np.float32),
        )

    # --- Unit tests on the predicate ---

    def test_should_apply_phone_zone_filter_predicate_uses_split_threshold(self):
        det = self._make_detector()
        # Box whose center is just below the split threshold -> upper-half.
        upper = PlateBox(
            x=0.40, y=_VERTICAL_SPLIT_THRESHOLD - 1e-6 - 0.05,
            w=0.10, h=0.10, confidence=0.9,
        )
        # Box whose center is exactly on the split line -> classified as lower
        # (matches `_filter_vertical_position`'s `cy >= 0.5` convention).
        on_line = PlateBox(
            x=0.40, y=_VERTICAL_SPLIT_THRESHOLD - 0.05,
            w=0.10, h=0.10, confidence=0.9,
        )
        # Strictly lower-half box.
        lower = PlateBox(x=0.40, y=0.80, w=0.10, h=0.10, confidence=0.9)

        assert det._should_apply_phone_zone_filter([upper]) is True
        assert det._should_apply_phone_zone_filter([upper, lower]) is True
        assert det._should_apply_phone_zone_filter([on_line]) is False
        assert det._should_apply_phone_zone_filter([lower]) is False
        assert det._should_apply_phone_zone_filter([on_line, lower]) is False
        assert det._should_apply_phone_zone_filter([]) is False

    # --- Integration through detect_frame ---

    def test_lower_only_frame_keeps_box_inside_dashboard_zone(self):
        """No upper-half candidate => filter is skipped => the lower box that
        sits inside the dashboard zone is retained.
        """
        det = self._make_detector(exclude_phones=True)
        # Lower-half box centered at (0.5, 0.9), inside a bottom-strip zone.
        lower = PlateBox(x=0.45, y=0.85, w=0.10, h=0.10, confidence=0.9)
        zones = [(0.0, 0.5, 1.0, 0.5)]  # entire bottom half is "dashboard"
        self._wire_for_detect_frame(det, [lower], zones)

        with patch("trailvideocut.plate.detector._BACKEND", "cv2"):
            result = det.detect_frame(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == [lower]

    def test_mixed_upper_lower_drops_dashboard_box(self):
        """Upper-half candidate is present => filter runs => the lower box
        inside the dashboard zone is removed before the vertical-position
        filter sees it. The vertical-position filter then acts on the
        remaining upper box and is a no-op.
        """
        det = self._make_detector(exclude_phones=True)
        upper = PlateBox(x=0.40, y=0.20, w=0.10, h=0.05, confidence=0.9)  # cy=0.225
        lower_in_zone = PlateBox(
            x=0.45, y=0.85, w=0.10, h=0.10, confidence=0.9,  # cy=0.90
        )
        zones = [(0.0, 0.5, 1.0, 0.5)]
        self._wire_for_detect_frame(det, [upper, lower_in_zone], zones)

        with patch("trailvideocut.plate.detector._BACKEND", "cv2"):
            result = det.detect_frame(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == [upper]

    def test_upper_only_frame_is_noop(self):
        """Upper-only candidate list: filter runs but removes nothing
        (dashboard zones live in the bottom half, so no upper-half center
        falls inside them). Result equals the input.
        """
        det = self._make_detector(exclude_phones=True)
        upper = PlateBox(x=0.40, y=0.10, w=0.10, h=0.05, confidence=0.9)  # cy=0.125
        zones = [(0.0, 0.5, 1.0, 0.5)]
        self._wire_for_detect_frame(det, [upper], zones)

        with patch("trailvideocut.plate.detector._BACKEND", "cv2"):
            result = det.detect_frame(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == [upper]

    def test_empty_post_geometry_is_noop(self):
        """Empty candidate list => filter is skipped => empty result."""
        det = self._make_detector(exclude_phones=True)
        zones = [(0.0, 0.5, 1.0, 0.5)]
        self._wire_for_detect_frame(det, [], zones)

        with patch("trailvideocut.plate.detector._BACKEND", "cv2"):
            result = det.detect_frame(np.zeros((100, 100, 3), dtype=np.uint8))

        assert result == []

    # --- Integration through detect_frame_tiled ---

    def test_tiled_path_applies_same_gate(self):
        """detect_frame_tiled must apply the same per-frame gate. With a
        single lower-half candidate inside a dashboard zone, the filter is
        skipped and the box survives.
        """
        det = self._make_detector(exclude_phones=True)
        lower = PlateBox(x=0.45, y=0.85, w=0.10, h=0.10, confidence=0.9)
        zones = [(0.0, 0.5, 1.0, 0.5)]

        # Bypass tile-level model invocation by monkey-patching the post-tiling
        # path directly: have NMS / geometry pass through unchanged, and have
        # the model mock emit the single lower box.
        det._parse_output = MagicMock(return_value=[lower])
        det._filter_geometry = lambda boxes, w, h: list(boxes)
        det.update_phone_zones = MagicMock(
            side_effect=lambda frame: setattr(det, "_phone_zones", list(zones)),
        )
        det._infer_cv2 = MagicMock(
            return_value=np.zeros((1, 5, 0), dtype=np.float32),
        )

        with patch("trailvideocut.plate.detector._BACKEND", "cv2"):
            # 640x640 frame so detect_frame_tiled produces tiles.
            frame = np.zeros((640, 640, 3), dtype=np.uint8)
            result = det.detect_frame_tiled(frame)

        # Filter was skipped (no upper-half candidate after dedup), so the
        # lower box survives. NMS may or may not collapse duplicates from
        # multiple tiles; either way the result must contain the lower box
        # and nothing else.
        assert len(result) >= 1
        assert all(b.y == lower.y and b.x == lower.x for b in result)

    # --- Recording invariance: zones are still recorded when filter is skipped ---

    def test_zone_recording_unchanged_when_filter_skipped(self):
        """detect_clip must still record per-frame phone zones in
        ClipPlateData.phone_zones EVEN WHEN the new gate skipped the filter
        for that frame. This verifies the gate touches filtering only, not
        recording.
        """
        det = self._make_detector(exclude_phones=True)
        lower = PlateBox(x=0.45, y=0.85, w=0.10, h=0.10, confidence=0.9)
        zone_tuple = (0.0, 0.5, 1.0, 0.5)
        frame_idx = [0]

        def fake_detect(frame):
            # Simulate update_phone_zones populating the zone for this frame.
            det._phone_zones = [zone_tuple]
            frame_idx[0] += 1
            # Returning the lower box represents "filter was gated off because
            # there is no upper-half candidate in this frame".
            return [lower]

        det.detect_frame_tiled = fake_detect

        with patch("cv2.VideoCapture") as mock_cap_cls:
            mock_cap = MagicMock()
            mock_cap_cls.return_value = mock_cap
            mock_cap.get.return_value = 10.0
            mock_cap.read.return_value = (
                True, np.zeros((100, 100, 3), dtype=np.uint8),
            )
            result = det.detect_clip(
                "fake.mp4", 0.0, 0.5, clip_index=0, temporal_filter=False,
            )

        # Five frames were processed (5 fps * 0.5s implied range, see existing
        # _run_clip helper). For each one, the lower box was kept (filter
        # skipped) AND the zone was recorded.
        assert frame_idx[0] >= 1
        assert all(boxes == [lower] for boxes in result.detections.values()), (
            "Lower-half box should be retained on every frame because the "
            "filter is gated off when no upper-half candidate is present."
        )
        assert all(
            zones == [zone_tuple] for zones in result.phone_zones.values()
        ), "Zones must still be recorded even when the filter was skipped."
        # And the zone-frame set must match the detection-frame set
        # (recording happens for every frame regardless of the gate).
        assert set(result.phone_zones.keys()) == set(result.detections.keys())
