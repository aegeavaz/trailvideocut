"""Tests for GPU batch scorers — parity with CPU scorers."""

import numpy as np
import pytest

from smartcut.video.scorers import (
    score_brightness_change,
    score_color_histogram_change,
    score_edge_variance,
)

try:
    import cupy  # noqa: F401

    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False

pytestmark = pytest.mark.skipif(not CUPY_AVAILABLE, reason="CuPy not installed")


@pytest.fixture
def gpu_scorer():
    from smartcut.video.scorers_gpu import GPUFrameScorer

    return GPUFrameScorer(batch_size=32)


def _random_gray(seed: int = 0) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return rng.randint(0, 256, (360, 640), dtype=np.uint8)


def _random_color(seed: int = 0) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return rng.randint(0, 256, (360, 640, 3), dtype=np.uint8)


def _uniform_gray(value: int = 128) -> np.ndarray:
    return np.full((360, 640), value, dtype=np.uint8)


def _uniform_color(bgr: tuple[int, int, int] = (128, 128, 128)) -> np.ndarray:
    frame = np.empty((360, 640, 3), dtype=np.uint8)
    for ch in range(3):
        frame[:, :, ch] = bgr[ch]
    return frame


class TestEdgeVarianceParity:
    """GPU edge variance should approximate CPU Canny-based edge density."""

    def test_noisy_frames(self, gpu_scorer):
        """Both methods should give high scores for noisy/detailed frames."""
        grays = [_random_gray(seed=i) for i in range(5)]
        colors = [_random_color(seed=i) for i in range(5)]

        gpu_results = gpu_scorer.score_batch(grays, colors)
        for i, gray in enumerate(grays):
            cpu_score = score_edge_variance(gray)
            gpu_score = gpu_results[i]["edge_variance"]
            # Both should be non-trivial for random frames
            assert gpu_score > 0.0
            assert cpu_score > 0.0

    def test_uniform_frames_low_edges(self, gpu_scorer):
        """Uniform frames should have near-zero edge scores on both."""
        grays = [_uniform_gray(100), _uniform_gray(200)]
        colors = [_uniform_color((100, 100, 100)), _uniform_color((200, 200, 200))]

        gpu_results = gpu_scorer.score_batch(grays, colors)
        for i, gray in enumerate(grays):
            cpu_score = score_edge_variance(gray)
            gpu_score = gpu_results[i]["edge_variance"]
            assert gpu_score < 0.01, f"GPU edge on uniform frame should be ~0, got {gpu_score}"
            assert cpu_score < 0.01, f"CPU edge on uniform frame should be ~0, got {cpu_score}"

    def test_relative_ordering(self, gpu_scorer):
        """Noisy frame should score higher than uniform for both methods."""
        grays = [_uniform_gray(128), _random_gray(42)]
        colors = [_uniform_color(), _random_color(42)]

        gpu_results = gpu_scorer.score_batch(grays, colors)
        assert gpu_results[1]["edge_variance"] > gpu_results[0]["edge_variance"]


class TestBrightnessChangeParity:
    """GPU brightness change should match CPU within tolerance."""

    def test_parity_random_frames(self, gpu_scorer):
        grays = [_random_gray(seed=i) for i in range(10)]
        colors = [_random_color(seed=i) for i in range(10)]

        gpu_results = gpu_scorer.score_batch(grays, colors)

        for i in range(1, len(grays)):
            cpu_score = score_brightness_change(grays[i - 1], grays[i])
            gpu_score = gpu_results[i]["brightness_change"]
            assert abs(gpu_score - cpu_score) < 0.15, (
                f"Frame {i}: GPU={gpu_score:.4f} vs CPU={cpu_score:.4f}"
            )

    def test_first_frame_zero(self, gpu_scorer):
        grays = [_random_gray(0), _random_gray(1)]
        colors = [_random_color(0), _random_color(1)]
        results = gpu_scorer.score_batch(grays, colors)
        assert results[0]["brightness_change"] == 0.0

    def test_large_brightness_delta(self, gpu_scorer):
        grays = [_uniform_gray(0), _uniform_gray(255)]
        colors = [_uniform_color((0, 0, 0)), _uniform_color((255, 255, 255))]
        results = gpu_scorer.score_batch(grays, colors)
        assert results[1]["brightness_change"] == pytest.approx(1.0, abs=0.01)


class TestColorChangeParity:
    """GPU color change should approximate CPU histogram correlation."""

    def test_identical_frames_zero(self, gpu_scorer):
        gray = _random_gray(7)
        color = _random_color(7)
        results = gpu_scorer.score_batch([gray, gray], [color, color])
        assert results[1]["color_change"] < 0.05

    def test_different_frames_nonzero(self, gpu_scorer):
        grays = [_random_gray(0), _random_gray(99)]
        colors = [_random_color(0), _random_color(99)]
        results = gpu_scorer.score_batch(grays, colors)
        assert results[1]["color_change"] > 0.0

    def test_parity_with_cpu(self, gpu_scorer):
        grays = [_random_gray(seed=i) for i in range(5)]
        colors = [_random_color(seed=i) for i in range(5)]

        gpu_results = gpu_scorer.score_batch(grays, colors)

        for i in range(1, len(colors)):
            cpu_score = score_color_histogram_change(colors[i - 1], colors[i])
            gpu_score = gpu_results[i]["color_change"]
            # Wider tolerance — different histogram implementations
            assert abs(gpu_score - cpu_score) < 0.30, (
                f"Frame {i}: GPU={gpu_score:.4f} vs CPU={cpu_score:.4f}"
            )

    def test_first_frame_zero(self, gpu_scorer):
        grays = [_random_gray(0)]
        colors = [_random_color(0)]
        results = gpu_scorer.score_batch(grays, colors)
        assert results[0]["color_change"] == 0.0


class TestBatchChunking:
    """Verify chunking produces consistent results."""

    def test_small_vs_large_batch(self):
        from smartcut.video.scorers_gpu import GPUFrameScorer

        grays = [_random_gray(seed=i) for i in range(20)]
        colors = [_random_color(seed=i) for i in range(20)]

        scorer_small = GPUFrameScorer(batch_size=4)
        scorer_large = GPUFrameScorer(batch_size=64)

        results_small = scorer_small.score_batch(grays, colors)
        results_large = scorer_large.score_batch(grays, colors)

        for i in range(20):
            for key in ("edge_variance", "brightness_change", "color_change"):
                assert abs(results_small[i][key] - results_large[i][key]) < 0.01, (
                    f"Frame {i} {key}: small={results_small[i][key]:.4f} "
                    f"vs large={results_large[i][key]:.4f}"
                )
