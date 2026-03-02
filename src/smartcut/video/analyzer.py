import bisect
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from smartcut.config import SmartCutConfig
from smartcut.video.models import InterestScore, VideoSegment
from smartcut.video.scene_detect import SceneBoundaryDetector
from smartcut.video.scorers import (
    score_brightness_change,
    score_color_histogram_change,
    score_edge_variance,
    score_optical_flow,
)


def _score_single_frame(
    index: int,
    current_time: float,
    gray: np.ndarray,
    color: np.ndarray,
    prev_gray: np.ndarray | None,
    prev_color: np.ndarray | None,
) -> tuple[int, float, dict[str, float]]:
    """Score a single frame with all 4 scorers. Thread-safe, no shared mutable state.

    Returns (index, time, scores) so results can be placed back in order.
    """
    scores: dict[str, float] = {}
    if prev_gray is not None:
        scores["optical_flow"] = score_optical_flow(prev_gray, gray)
        scores["color_change"] = score_color_histogram_change(prev_color, color)
        scores["brightness_change"] = score_brightness_change(prev_gray, gray)
    scores["edge_variance"] = score_edge_variance(gray)
    return (index, current_time, scores)


class VideoAnalyzer:
    """Analyze video for visual interest scoring using overlapping windows."""

    def __init__(self, config: SmartCutConfig):
        self.config = config
        self.source_fps: float = 30.0

    def analyze(self) -> list[VideoSegment]:
        """Analyze entire video, return scored segments with overlapping windows.

        Runs scene detection concurrently with frame reading+scoring. Scene
        detection and frame reading each open their own VideoCapture, so they
        run in parallel without blocking each other.
        """
        # Run scene detection and frame reading+scoring concurrently
        with ThreadPoolExecutor(max_workers=2) as executor:
            boundary_future = executor.submit(self._detect_boundaries)
            score_future = executor.submit(self._read_and_score)

            frame_data = score_future.result()
            boundaries = boundary_future.result()

        if not frame_data:
            return []

        video_duration = frame_data[-1][0] + (1.0 / self.config.analysis_fps)
        segments = self._build_overlapping_windows(frame_data, video_duration, boundaries)
        return self._normalize_segments(segments)

    def _detect_boundaries(self) -> list[float]:
        """Run PySceneDetect's optimized scene detection (auto-downscales internally)."""
        detector = SceneBoundaryDetector(self.config)
        return detector.detect_boundaries()

    def _read_and_score(self) -> list[tuple[float, dict[str, float]]]:
        """Read sampled frames and score them with overlapped parallelism.

        The main thread reads and preprocesses frames sequentially. As each
        sampled frame is read, its scoring job is immediately submitted to a
        thread pool. Scoring runs concurrently with reading — by the time all
        frames are read, most scoring is already done.
        """
        cap = cv2.VideoCapture(str(self.config.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.config.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        self.source_fps = fps or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(1, int(fps / self.config.analysis_fps))

        num_workers = max(4, (os.cpu_count() or 4) - 2)
        raw_frames: list[tuple[float, np.ndarray, np.ndarray]] = []
        pending: list[tuple[int, object]] = []
        frame_idx = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task(
                f"Analyzing video ({num_workers} scoring threads)",
                total=total_frames,
            )

            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    if frame_idx % sample_interval == 0:
                        current_time = frame_idx / fps
                        frame_small = cv2.resize(frame, (640, 360))
                        gray_small = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)

                        i = len(raw_frames)
                        prev_gray = raw_frames[-1][1] if raw_frames else None
                        prev_color = raw_frames[-1][2] if raw_frames else None
                        raw_frames.append((current_time, gray_small, frame_small))

                        # Submit scoring immediately — overlaps with reading
                        future = executor.submit(
                            _score_single_frame, i, current_time,
                            gray_small, frame_small, prev_gray, prev_color,
                        )
                        pending.append((i, future))

                    frame_idx += 1
                    progress.update(task, completed=frame_idx)

                progress.update(task, completed=total_frames)

                # Collect scoring results (most are already done by now)
                frame_data: list[tuple[float, dict[str, float]] | None] = [None] * len(raw_frames)
                for i, future in pending:
                    index, current_time, scores = future.result()
                    frame_data[index] = (current_time, scores)

        cap.release()
        return frame_data

    def _build_overlapping_windows(
        self,
        frame_data: list[tuple[float, dict[str, float]]],
        video_duration: float,
        boundaries: list[float],
    ) -> list[VideoSegment]:
        """Build overlapping windows using binary search for O(M*logN) performance."""
        hop = self.config.segment_hop
        window = self.config.segment_window
        segments: list[VideoSegment] = []

        # Extract sorted times array for binary search
        times = [t for t, _ in frame_data]
        sorted_boundaries = sorted(boundaries)

        window_start = 0.0
        while window_start < video_duration:
            window_end = min(window_start + window, video_duration)

            # Binary search for frame slice boundaries
            lo = bisect.bisect_left(times, window_start)
            hi = bisect.bisect_left(times, window_end)

            # Gather frame scores within this window
            window_scores: dict[str, list[float]] = {
                "optical_flow": [],
                "color_change": [],
                "edge_variance": [],
                "brightness_change": [],
            }
            for i in range(lo, hi):
                _, scores = frame_data[i]
                for key in window_scores:
                    if key in scores:
                        window_scores[key].append(scores[key])

            if any(window_scores.values()):
                segment = self._finalize_window(
                    window_start, window_end, window_scores, sorted_boundaries
                )
                segments.append(segment)

            window_start += hop

        return segments

    def _finalize_window(
        self,
        start: float,
        end: float,
        scores: dict[str, list[float]],
        boundaries: list[float],
    ) -> VideoSegment:
        """Build a VideoSegment from accumulated window scores."""

        def safe_mean(arr: list[float]) -> float:
            return float(np.mean(arr)) if arr else 0.0

        interest = InterestScore(
            optical_flow=safe_mean(scores["optical_flow"]),
            color_change=safe_mean(scores["color_change"]),
            edge_variance=safe_mean(scores["edge_variance"]),
            brightness_change=safe_mean(scores["brightness_change"]),
        )
        # Binary search for boundary check: O(log B) instead of O(B)
        lo = bisect.bisect_left(boundaries, start)
        near_boundary = lo < len(boundaries) and boundaries[lo] <= end
        return VideoSegment(
            start_time=start, end_time=end, interest=interest, scene_boundary_near=near_boundary
        )

    def _normalize_segments(self, segments: list[VideoSegment]) -> list[VideoSegment]:
        """Min-max normalize each score dimension across all segments."""
        if not segments:
            return segments

        for attr in ("optical_flow", "color_change", "edge_variance", "brightness_change"):
            values = [getattr(s.interest, attr) for s in segments]
            vmin, vmax = min(values), max(values)
            rng = vmax - vmin if vmax > vmin else 1.0
            for s in segments:
                normalized = (getattr(s.interest, attr) - vmin) / rng
                setattr(s.interest, attr, normalized)

        return segments
