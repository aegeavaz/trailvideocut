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
