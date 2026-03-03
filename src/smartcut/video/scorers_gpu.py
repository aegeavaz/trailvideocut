"""GPU-accelerated batch frame scorers using CuPy.

Provides edge variance, brightness change, and color change scoring on the GPU.
Optical flow remains on CPU (no CuPy equivalent for Farneback).
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cupy as cp
    import cupyx.scipy.ndimage as cpndimage

    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False


class GPUFrameScorer:
    """Batch scorer that processes N frames on the GPU in one transfer.

    Usage::

        scorer = GPUFrameScorer(batch_size=64)
        results = scorer.score_batch(grays, colors)
        # results: list of dicts with keys edge_variance, brightness_change, color_change
    """

    def __init__(self, batch_size: int = 64):
        if not CUPY_AVAILABLE:
            raise RuntimeError("CuPy is not installed — cannot use GPU scoring")
        self.batch_size = batch_size

    def score_batch(
        self,
        grays: list[np.ndarray],
        colors: list[np.ndarray],
    ) -> list[dict[str, float]]:
        """Score all frames in batches, returning per-frame score dicts.

        Args:
            grays: List of grayscale frames (H, W), uint8.
            colors: List of BGR color frames (H, W, 3), uint8.

        Returns:
            List of dicts with keys: edge_variance, brightness_change, color_change.
            First frame has brightness_change=0.0 and color_change=0.0.
        """
        n = len(grays)
        if n == 0:
            return []

        all_edge = np.zeros(n, dtype=np.float64)
        all_brightness = np.zeros(n, dtype=np.float64)
        all_color = np.zeros(n, dtype=np.float64)

        # Process in chunks to limit GPU memory usage
        for start in range(0, n, self.batch_size):
            end = min(start + self.batch_size, n)
            chunk_grays = grays[start:end]
            chunk_colors = colors[start:end]

            edge_scores = self._batch_edge_variance(chunk_grays)
            brightness_scores = self._batch_brightness_change(chunk_grays, is_first_chunk=(start == 0))
            color_scores = self._batch_color_change(chunk_colors, is_first_chunk=(start == 0))

            all_edge[start:end] = edge_scores
            all_brightness[start:end] = brightness_scores
            all_color[start:end] = color_scores

            # Handle cross-chunk brightness/color change for the first frame of non-first chunks
            if start > 0:
                # Recompute the boundary frame's brightness change
                prev_gray_gpu = cp.asarray(grays[start - 1], dtype=cp.float32)
                curr_gray_gpu = cp.asarray(grays[start], dtype=cp.float32)
                diff = float(cp.abs(cp.mean(curr_gray_gpu) - cp.mean(prev_gray_gpu)).get()) / 255.0
                all_brightness[start] = diff

                # Recompute the boundary frame's color change
                prev_color_np = colors[start - 1]
                curr_color_np = colors[start]
                all_color[start] = self._single_color_change(prev_color_np, curr_color_np)

            # Free GPU memory between chunks
            cp.get_default_memory_pool().free_all_blocks()

        results: list[dict[str, float]] = []
        for i in range(n):
            results.append({
                "edge_variance": float(all_edge[i]),
                "brightness_change": float(all_brightness[i]),
                "color_change": float(all_color[i]),
            })

        return results

    def _batch_edge_variance(self, grays: list[np.ndarray]) -> np.ndarray:
        """Compute edge density for a batch of grayscale frames using Sobel filters.

        Approximates Canny edge detection via Sobel magnitude thresholding.
        """
        batch = cp.asarray(np.stack(grays), dtype=cp.float32)  # (N, H, W)

        # Sobel in X and Y for each frame
        sobel_x = cp.empty_like(batch)
        sobel_y = cp.empty_like(batch)
        for i in range(batch.shape[0]):
            sobel_x[i] = cpndimage.sobel(batch[i], axis=1)
            sobel_y[i] = cpndimage.sobel(batch[i], axis=0)

        magnitude = cp.sqrt(sobel_x ** 2 + sobel_y ** 2)

        # Threshold to approximate binary edge map (similar to Canny)
        threshold = 50.0
        edge_mask = (magnitude > threshold).astype(cp.float32)

        # Mean edge density per frame
        scores = cp.mean(edge_mask, axis=(1, 2))
        return scores.get()

    def _batch_brightness_change(
        self, grays: list[np.ndarray], is_first_chunk: bool
    ) -> np.ndarray:
        """Compute brightness change between consecutive frames."""
        batch = cp.asarray(np.stack(grays), dtype=cp.float32)  # (N, H, W)
        means = cp.mean(batch, axis=(1, 2))  # (N,)

        diffs = cp.abs(cp.diff(means)) / 255.0  # (N-1,)

        # First frame in first chunk has no predecessor
        if is_first_chunk:
            result = cp.zeros(len(grays), dtype=cp.float64)
            result[1:] = diffs
        else:
            # First frame's diff will be recomputed at the boundary
            result = cp.zeros(len(grays), dtype=cp.float64)
            result[1:] = diffs
            result[0] = 0.0  # placeholder, overwritten by caller

        return result.get()

    def _batch_color_change(
        self, colors: list[np.ndarray], is_first_chunk: bool
    ) -> np.ndarray:
        """Compute color histogram change between consecutive frames.

        Uses per-channel histograms with correlation comparison on GPU.
        """
        n = len(colors)
        scores = np.zeros(n, dtype=np.float64)

        # Compute per-channel histograms on GPU
        batch_bgr = cp.asarray(np.stack(colors), dtype=cp.float32)  # (N, H, W, 3)

        # Compute 32-bin histograms per channel (B, G, R) for each frame
        n_bins = 32
        histograms = cp.zeros((n, 3, n_bins), dtype=cp.float32)

        for ch in range(3):
            channel = batch_bgr[:, :, :, ch]  # (N, H, W)
            # Bin indices for each pixel
            bins = cp.clip((channel * n_bins / 256.0).astype(cp.int32), 0, n_bins - 1)
            for b in range(n_bins):
                histograms[:, ch, b] = cp.mean((bins == b).astype(cp.float32), axis=(1, 2))

        # Normalize histograms per frame per channel
        norms = cp.sqrt(cp.sum(histograms ** 2, axis=2, keepdims=True))
        norms = cp.maximum(norms, 1e-10)
        histograms = histograms / norms

        # Correlation between consecutive frames (per-channel dot product, then average)
        start_idx = 1
        for i in range(start_idx, n):
            per_ch_corr = cp.sum(histograms[i] * histograms[i - 1], axis=1)  # (3,)
            corr = cp.mean(per_ch_corr)
            scores[i] = float(cp.maximum(0.0, 1.0 - corr).get())

        if is_first_chunk:
            scores[0] = 0.0

        return scores

    def _single_color_change(self, prev_bgr: np.ndarray, curr_bgr: np.ndarray) -> float:
        """Compute color change between two frames (for cross-chunk boundaries)."""
        n_bins = 32

        prev_gpu = cp.asarray(prev_bgr, dtype=cp.float32)
        curr_gpu = cp.asarray(curr_bgr, dtype=cp.float32)

        prev_hist = cp.zeros((3, n_bins), dtype=cp.float32)
        curr_hist = cp.zeros((3, n_bins), dtype=cp.float32)

        for ch in range(3):
            prev_bins = cp.clip((prev_gpu[:, :, ch] * n_bins / 256.0).astype(cp.int32), 0, n_bins - 1)
            curr_bins = cp.clip((curr_gpu[:, :, ch] * n_bins / 256.0).astype(cp.int32), 0, n_bins - 1)
            for b in range(n_bins):
                prev_hist[ch, b] = cp.mean((prev_bins == b).astype(cp.float32))
                curr_hist[ch, b] = cp.mean((curr_bins == b).astype(cp.float32))

        prev_norm = cp.sqrt(cp.sum(prev_hist ** 2, axis=1, keepdims=True))
        curr_norm = cp.sqrt(cp.sum(curr_hist ** 2, axis=1, keepdims=True))
        prev_hist = prev_hist / cp.maximum(prev_norm, 1e-10)
        curr_hist = curr_hist / cp.maximum(curr_norm, 1e-10)

        per_ch_corr = cp.sum(prev_hist * curr_hist, axis=1)  # (3,)
        corr = cp.mean(per_ch_corr)
        return float(cp.maximum(0.0, 1.0 - corr).get())
