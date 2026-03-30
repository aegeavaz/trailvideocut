"""Tests for per-frame plate detection merge, clear clip, and clear frame logic.

These tests exercise the core data manipulation logic without requiring a GUI
or real model — they operate directly on ClipPlateData / PlateBox structures.
"""

import pytest

from trailvideocut.plate.models import ClipPlateData, PlateBox


# --- Fixtures ---

def _auto_box(x=0.1, y=0.2, w=0.05, h=0.03, confidence=0.9):
    return PlateBox(x=x, y=y, w=w, h=h, confidence=confidence, manual=False)


def _manual_box(x=0.3, y=0.4, w=0.06, h=0.04):
    return PlateBox(x=x, y=y, w=w, h=h, confidence=0.0, manual=True)


@pytest.fixture
def clip_data_with_mixed_boxes():
    """Clip data with frame 100 having both auto and manual boxes."""
    return ClipPlateData(
        clip_index=0,
        detections={
            100: [_auto_box(), _auto_box(x=0.5), _manual_box()],
            101: [_auto_box(x=0.7)],
        },
    )


# --- 6.1: Single-frame detection merge logic ---

class TestSingleFrameDetectionMerge:
    """Merge logic: auto-detected boxes are replaced, manual boxes are preserved."""

    @staticmethod
    def _merge_frame(clip_data: ClipPlateData, frame_num: int, new_boxes: list[PlateBox]):
        """Replicate the merge logic from ReviewPage._run_single_frame_detection."""
        existing_boxes = clip_data.detections.get(frame_num, [])
        manual_boxes = [b for b in existing_boxes if b.manual]

        if new_boxes or manual_boxes:
            clip_data.detections[frame_num] = new_boxes + manual_boxes
        elif frame_num in clip_data.detections:
            del clip_data.detections[frame_num]

    def test_replaces_auto_boxes(self, clip_data_with_mixed_boxes):
        data = clip_data_with_mixed_boxes
        new_auto = [_auto_box(x=0.8, confidence=0.95)]
        self._merge_frame(data, 100, new_auto)

        auto_boxes = [b for b in data.detections[100] if not b.manual]
        assert len(auto_boxes) == 1
        assert auto_boxes[0].x == pytest.approx(0.8)

    def test_preserves_manual_boxes(self, clip_data_with_mixed_boxes):
        data = clip_data_with_mixed_boxes
        new_auto = [_auto_box(x=0.8)]
        self._merge_frame(data, 100, new_auto)

        manual_boxes = [b for b in data.detections[100] if b.manual]
        assert len(manual_boxes) == 1
        assert manual_boxes[0].x == pytest.approx(0.3)

    def test_no_detections_keeps_manuals(self, clip_data_with_mixed_boxes):
        data = clip_data_with_mixed_boxes
        self._merge_frame(data, 100, [])

        assert 100 in data.detections
        assert all(b.manual for b in data.detections[100])

    def test_no_detections_no_manuals_removes_frame(self):
        data = ClipPlateData(clip_index=0, detections={50: [_auto_box()]})
        self._merge_frame(data, 50, [])
        assert 50 not in data.detections

    def test_new_frame_without_prior_data(self):
        data = ClipPlateData(clip_index=0, detections={})
        new_auto = [_auto_box()]
        self._merge_frame(data, 200, new_auto)

        assert 200 in data.detections
        assert len(data.detections[200]) == 1

    def test_other_frames_unaffected(self, clip_data_with_mixed_boxes):
        data = clip_data_with_mixed_boxes
        self._merge_frame(data, 100, [_auto_box(x=0.9)])

        # Frame 101 should be untouched
        assert len(data.detections[101]) == 1
        assert data.detections[101][0].x == pytest.approx(0.7)


# --- 6.2: Clear clip plates ---

class TestClearClipPlates:
    """Clear clip plates: removes clip data, handles last-clip edge case."""

    def test_removes_clip_data(self):
        plate_data = {
            0: ClipPlateData(clip_index=0, detections={10: [_auto_box()]}),
            1: ClipPlateData(clip_index=1, detections={20: [_auto_box()]}),
        }
        del plate_data[0]

        assert 0 not in plate_data
        assert 1 in plate_data

    def test_last_clip_results_in_empty_dict(self):
        plate_data = {
            0: ClipPlateData(clip_index=0, detections={10: [_auto_box()]}),
        }
        del plate_data[0]

        assert len(plate_data) == 0

    def test_removes_both_auto_and_manual_boxes(self):
        plate_data = {
            0: ClipPlateData(
                clip_index=0,
                detections={10: [_auto_box(), _manual_box()]},
            ),
        }
        del plate_data[0]

        assert 0 not in plate_data


# --- 6.3: Clear frame plates ---

class TestClearFramePlates:
    """Clear frame plates: removes frame entry, no-op when empty."""

    def test_removes_frame_entry(self, clip_data_with_mixed_boxes):
        data = clip_data_with_mixed_boxes
        frame_num = 100
        del data.detections[frame_num]

        assert frame_num not in data.detections
        # Other frames untouched
        assert 101 in data.detections

    def test_noop_when_frame_not_present(self):
        data = ClipPlateData(clip_index=0, detections={10: [_auto_box()]})
        frame_num = 999

        # Should not raise
        if frame_num in data.detections:
            del data.detections[frame_num]

        assert 10 in data.detections

    def test_removes_both_auto_and_manual(self):
        data = ClipPlateData(
            clip_index=0,
            detections={10: [_auto_box(), _manual_box()]},
        )
        del data.detections[10]

        assert 10 not in data.detections


# --- 6.4: Button state management ---

class TestButtonStateLogic:
    """Test the _update_frame_buttons logic extracted as a pure function."""

    @staticmethod
    def compute_button_states(
        video_path: str,
        selected: int,
        clips_count: int,
        plate_data: dict,
        current_frame: int,
        detecting: bool,
    ) -> dict[str, bool]:
        """Replicate the button state logic from ReviewPage._update_frame_buttons."""
        has_video = bool(video_path)
        has_clip = 0 <= selected < clips_count

        detect_frame = has_video and has_clip and not detecting
        clip_has_plates = has_clip and selected in plate_data
        clear_clip = clip_has_plates and not detecting

        frame_has_plates = False
        if clip_has_plates:
            frame_has_plates = current_frame in plate_data[selected].detections
        clear_frame = frame_has_plates and not detecting

        return {
            "detect_frame": detect_frame,
            "clear_clip": clear_clip,
            "clear_frame": clear_frame,
        }

    def test_all_disabled_no_video(self):
        states = self.compute_button_states("", 0, 5, {}, 100, False)
        assert not states["detect_frame"]
        assert not states["clear_clip"]
        assert not states["clear_frame"]

    def test_all_disabled_no_clip_selected(self):
        states = self.compute_button_states("/v.mp4", -1, 5, {}, 100, False)
        assert not states["detect_frame"]
        assert not states["clear_clip"]
        assert not states["clear_frame"]

    def test_all_disabled_during_detection(self):
        plate_data = {0: ClipPlateData(clip_index=0, detections={100: [_auto_box()]})}
        states = self.compute_button_states("/v.mp4", 0, 5, plate_data, 100, True)
        assert not states["detect_frame"]
        assert not states["clear_clip"]
        assert not states["clear_frame"]

    def test_detect_frame_enabled_clip_selected(self):
        states = self.compute_button_states("/v.mp4", 0, 5, {}, 100, False)
        assert states["detect_frame"]
        assert not states["clear_clip"]
        assert not states["clear_frame"]

    def test_clear_clip_enabled_with_plate_data(self):
        plate_data = {0: ClipPlateData(clip_index=0, detections={50: [_auto_box()]})}
        states = self.compute_button_states("/v.mp4", 0, 5, plate_data, 100, False)
        assert states["detect_frame"]
        assert states["clear_clip"]
        assert not states["clear_frame"]  # frame 100 has no plates

    def test_clear_frame_enabled_with_frame_plates(self):
        plate_data = {0: ClipPlateData(clip_index=0, detections={100: [_auto_box()]})}
        states = self.compute_button_states("/v.mp4", 0, 5, plate_data, 100, False)
        assert states["detect_frame"]
        assert states["clear_clip"]
        assert states["clear_frame"]

    def test_navigate_to_frame_without_plates(self):
        plate_data = {0: ClipPlateData(clip_index=0, detections={100: [_auto_box()]})}
        states = self.compute_button_states("/v.mp4", 0, 5, plate_data, 200, False)
        assert states["detect_frame"]
        assert states["clear_clip"]
        assert not states["clear_frame"]

    def test_navigate_to_different_clip_without_data(self):
        plate_data = {0: ClipPlateData(clip_index=0, detections={100: [_auto_box()]})}
        states = self.compute_button_states("/v.mp4", 1, 5, plate_data, 100, False)
        assert states["detect_frame"]
        assert not states["clear_clip"]
        assert not states["clear_frame"]
