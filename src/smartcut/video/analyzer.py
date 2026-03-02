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
    """Analyze video for visual interest scoring."""

    def __init__(self, config: SmartCutConfig):
        self.config = config

    def analyze(self) -> list[VideoSegment]:
        """Analyze entire video, return scored segments."""
        # Step 1: Detect scene boundaries
        boundary_detector = SceneBoundaryDetector(self.config)
        boundaries = boundary_detector.detect_boundaries()

        # Step 2: Sample frames and score windows
        cap = cv2.VideoCapture(str(self.config.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.config.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_duration = total_frames / fps

        sample_interval = max(1, int(fps / self.config.analysis_fps))

        segments: list[VideoSegment] = []
        prev_gray: np.ndarray | None = None
        prev_frame: np.ndarray | None = None

        window_scores: dict[str, list[float]] = {
            "optical_flow": [],
            "color_change": [],
            "edge_variance": [],
            "brightness_change": [],
        }
        window_start_time = 0.0
        frame_idx = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task("Analyzing video frames", total=total_frames)

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                progress.update(task, advance=1)

                if frame_idx % sample_interval != 0:
                    frame_idx += 1
                    continue

                current_time = frame_idx / fps

                # Downsample for performance
                frame_small = cv2.resize(frame, (640, 360))
                gray_small = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)

                if prev_gray is not None:
                    window_scores["optical_flow"].append(
                        score_optical_flow(prev_gray, gray_small)
                    )
                    window_scores["color_change"].append(
                        score_color_histogram_change(prev_frame, frame_small)
                    )
                    window_scores["brightness_change"].append(
                        score_brightness_change(prev_gray, gray_small)
                    )
                window_scores["edge_variance"].append(score_edge_variance(gray_small))

                # Check if window is complete
                if current_time - window_start_time >= self.config.segment_window:
                    segment = self._finalize_window(
                        window_start_time, current_time, window_scores, boundaries
                    )
                    segments.append(segment)
                    window_start_time = current_time
                    window_scores = {k: [] for k in window_scores}

                prev_gray = gray_small
                prev_frame = frame_small
                frame_idx += 1

        cap.release()

        # Finalize last partial window
        if any(window_scores.values()):
            final_time = total_frames / fps
            segment = self._finalize_window(
                window_start_time, final_time, window_scores, boundaries
            )
            segments.append(segment)

        return self._normalize_segments(segments)

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
