"""Tests for frame-precise navigation math (position_to_frame / frame_to_position_ms).

Semantics under test:
- ``position_to_frame`` truncates (``int()``), matching the source-frame index
  that OpenCV/FFmpeg decode at that PTS.
- ``frame_to_position_ms`` ceils, so the target milliseconds land just past
  frame N's PTS — guaranteeing a round-trip back to frame N via ``int()``.
"""

import pytest

from trailvideocut.utils.frame_math import frame_to_position_ms, position_to_frame


COMMON_FPS = [23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0]


class TestPositionToFrame:
    def test_zero_position_is_frame_zero(self):
        for fps in COMMON_FPS:
            assert position_to_frame(0.0, fps) == 0

    def test_29_97_before_frame_one_boundary(self):
        # Frame 1's PTS at 29.97 fps is 33.37 ms. 33 ms is still inside frame 0.
        assert position_to_frame(0.033, 29.97) == 0

    def test_29_97_after_frame_one_boundary(self):
        # 34 ms is past frame 1's PTS (33.37 ms) → now in frame 1.
        assert position_to_frame(0.034, 29.97) == 1

    def test_exact_frame_boundary(self):
        # Position exactly at frame N's PTS yields frame N.
        for fps in COMMON_FPS:
            for n in (0, 1, 5, 42, 300):
                pos_s = n / fps
                assert position_to_frame(pos_s, fps) == n

    def test_end_of_video_2s_at_29_97(self):
        # 2.0 * 29.97 = 59.94 → truncates to frame 59.
        assert position_to_frame(2.0, 29.97) == 59

    def test_near_boundary_before_frame(self):
        fps = 30.0
        # A hair before frame 2's PTS → still in frame 1.
        assert position_to_frame((2 / fps) - 0.0001, fps) == 1

    def test_near_boundary_after_frame(self):
        fps = 30.0
        # A hair past frame 2's PTS → in frame 2.
        assert position_to_frame((2 / fps) + 0.0001, fps) == 2


class TestFrameToPositionMs:
    def test_frame_zero_is_zero_ms(self):
        for fps in COMMON_FPS:
            assert frame_to_position_ms(0, fps) == 0

    def test_29_97_frame_one_is_34ms(self):
        # 1 * 1000 / 29.97 = 33.37 → ceil = 34 (lands inside frame 1, not on the boundary).
        assert frame_to_position_ms(1, 29.97) == 34

    def test_30fps_frame_two_is_67ms(self):
        # 2 * 1000 / 30 = 66.67 → ceil = 67.
        assert frame_to_position_ms(2, 30.0) == 67

    def test_integer_fps_exact_boundary(self):
        # 25 fps: frame 1 at 40 ms exactly; ceil(40.0) = 40.
        assert frame_to_position_ms(1, 25.0) == 40


class TestRoundTrip:
    """``position_to_frame(frame_to_position_ms(n) / 1000) == n`` for all n ≥ 0."""

    @pytest.mark.parametrize("fps", COMMON_FPS)
    def test_round_trip_across_frames(self, fps):
        for n in range(0, 1800):
            ms = frame_to_position_ms(n, fps)
            back = position_to_frame(ms / 1000.0, fps)
            assert back == n, f"fps={fps}, frame={n}, ms={ms}, got back {back}"


class TestStepForwardBack:
    @staticmethod
    def _step_forward(position_ms: int, fps: float, duration_ms: int) -> int:
        current_frame = position_to_frame(position_ms / 1000.0, fps)
        target_ms = frame_to_position_ms(current_frame + 1, fps)
        return min(target_ms, duration_ms)

    @staticmethod
    def _step_back(position_ms: int, fps: float) -> int:
        current_frame = position_to_frame(position_ms / 1000.0, fps)
        target_ms = frame_to_position_ms(current_frame - 1, fps)
        return max(target_ms, 0)

    @pytest.mark.parametrize("fps", COMMON_FPS)
    def test_step_forward_increments_by_one(self, fps):
        pos_ms = 0
        duration_ms = 10_000_000
        for expected_frame in range(1, 200):
            pos_ms = self._step_forward(pos_ms, fps, duration_ms)
            landed_frame = position_to_frame(pos_ms / 1000.0, fps)
            assert landed_frame == expected_frame, (
                f"fps={fps}: after {expected_frame} steps, landed on frame {landed_frame}"
            )

    @pytest.mark.parametrize("fps", COMMON_FPS)
    def test_step_back_decrements_by_one(self, fps):
        start_frame = 200
        pos_ms = frame_to_position_ms(start_frame, fps)
        for i in range(1, 200):
            pos_ms = self._step_back(pos_ms, fps)
            landed_frame = position_to_frame(pos_ms / 1000.0, fps)
            expected_frame = start_frame - i
            assert landed_frame == expected_frame, (
                f"fps={fps}: after {i} back-steps, landed on frame {landed_frame}"
            )

    def test_step_back_clamps_at_zero(self):
        fps = 29.97
        pos_ms = self._step_back(0, fps)
        assert pos_ms == 0

    def test_step_forward_clamps_at_duration(self):
        fps = 29.97
        duration_ms = 1000
        pos_ms = frame_to_position_ms(30, fps)
        new_ms = self._step_forward(pos_ms, fps, duration_ms)
        assert new_ms <= duration_ms
