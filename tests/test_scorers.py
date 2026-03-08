import numpy as np

from trailvideocut.video.scorers import (
    score_brightness_change,
    score_color_histogram_change,
    score_edge_variance,
    score_optical_flow,
)


def _make_gray_frame(value: int = 128, h: int = 360, w: int = 640) -> np.ndarray:
    """Create a uniform grayscale frame."""
    return np.full((h, w), value, dtype=np.uint8)


def _make_color_frame(bgr: tuple = (128, 128, 128), h: int = 360, w: int = 640) -> np.ndarray:
    """Create a uniform color frame."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:] = bgr
    return frame


class TestOpticalFlow:
    def test_identical_frames_low_flow(self):
        gray = _make_gray_frame(128)
        score = score_optical_flow(gray, gray)
        assert score < 0.1

    def test_different_frames_higher_flow(self):
        prev = _make_gray_frame(100)
        # Create a shifted frame to simulate motion
        curr = np.zeros_like(prev)
        curr[:, 10:] = prev[:, :-10]
        score = score_optical_flow(prev, curr)
        assert score > 0.0


class TestColorHistogramChange:
    def test_identical_frames_zero_change(self):
        frame = _make_color_frame((100, 150, 200))
        score = score_color_histogram_change(frame, frame)
        assert score < 0.01

    def test_different_colors_high_change(self):
        red = _make_color_frame((0, 0, 255))
        blue = _make_color_frame((255, 0, 0))
        score = score_color_histogram_change(red, blue)
        assert score > 0.3


class TestEdgeVariance:
    def test_uniform_frame_low_edges(self):
        gray = _make_gray_frame(128)
        score = score_edge_variance(gray)
        assert score < 0.01

    def test_noisy_frame_has_edges(self):
        gray = np.random.randint(0, 255, (360, 640), dtype=np.uint8)
        score = score_edge_variance(gray)
        assert score > 0.0


class TestBrightnessChange:
    def test_identical_brightness_zero(self):
        gray = _make_gray_frame(128)
        score = score_brightness_change(gray, gray)
        assert abs(score) < 0.001

    def test_large_brightness_delta(self):
        dark = _make_gray_frame(20)
        bright = _make_gray_frame(220)
        score = score_brightness_change(dark, bright)
        assert score > 0.5

    def test_score_bounded_zero_one(self):
        black = _make_gray_frame(0)
        white = _make_gray_frame(255)
        score = score_brightness_change(black, white)
        assert 0.0 <= score <= 1.0
