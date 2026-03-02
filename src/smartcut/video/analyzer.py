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


class VideoAnalyzer:
    """Analyze video for visual interest scoring using overlapping windows."""

    def __init__(self, config: SmartCutConfig):
        self.config = config
        self.source_fps: float = 30.0

    def analyze(self) -> list[VideoSegment]:
        """Analyze entire video, return scored segments with overlapping windows."""
        # Step 1: Detect scene boundaries
        boundary_detector = SceneBoundaryDetector(self.config)
        boundaries = boundary_detector.detect_boundaries()

        # Step 2: Score all sampled frames into a flat list
        frame_data = self._score_frames()
        if not frame_data:
            return []

        video_duration = frame_data[-1][0] + (1.0 / self.config.analysis_fps)

        # Step 3: Build overlapping windows from frame_data
        segments = self._build_overlapping_windows(frame_data, video_duration, boundaries)

        return self._normalize_segments(segments)

    def _score_frames(self) -> list[tuple[float, dict[str, float]]]:
        """Pass 1: iterate frames, score each sampled frame into a flat list."""
        cap = cv2.VideoCapture(str(self.config.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.config.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        self.source_fps = fps or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(1, int(fps / self.config.analysis_fps))

        frame_data: list[tuple[float, dict[str, float]]] = []
        prev_gray: np.ndarray | None = None
        prev_frame: np.ndarray | None = None
        frame_idx = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task("Scoring video frames", total=total_frames)

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                progress.update(task, advance=1)

                if frame_idx % sample_interval != 0:
                    frame_idx += 1
                    continue

                current_time = frame_idx / fps
                frame_small = cv2.resize(frame, (640, 360))
                gray_small = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)

                scores: dict[str, float] = {}
                if prev_gray is not None:
                    scores["optical_flow"] = score_optical_flow(prev_gray, gray_small)
                    scores["color_change"] = score_color_histogram_change(
                        prev_frame, frame_small
                    )
                    scores["brightness_change"] = score_brightness_change(prev_gray, gray_small)
                scores["edge_variance"] = score_edge_variance(gray_small)

                frame_data.append((current_time, scores))
                prev_gray = gray_small
                prev_frame = frame_small
                frame_idx += 1

        cap.release()
        return frame_data

    def _build_overlapping_windows(
        self,
        frame_data: list[tuple[float, dict[str, float]]],
        video_duration: float,
        boundaries: list[float],
    ) -> list[VideoSegment]:
        """Pass 2: build overlapping windows at segment_hop intervals."""
        hop = self.config.segment_hop
        window = self.config.segment_window
        segments: list[VideoSegment] = []

        window_start = 0.0
        while window_start < video_duration:
            window_end = min(window_start + window, video_duration)

            # Gather frame scores within this window
            window_scores: dict[str, list[float]] = {
                "optical_flow": [],
                "color_change": [],
                "edge_variance": [],
                "brightness_change": [],
            }
            for t, scores in frame_data:
                if t < window_start:
                    continue
                if t >= window_end:
                    break
                for key in window_scores:
                    if key in scores:
                        window_scores[key].append(scores[key])

            if any(window_scores.values()):
                segment = self._finalize_window(
                    window_start, window_end, window_scores, boundaries
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
        near_boundary = any(start <= b <= end for b in boundaries)
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
