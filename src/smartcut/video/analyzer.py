import bisect
import json
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from smartcut.config import SmartCutConfig
from smartcut.gpu import detect_gpu
from smartcut.video.models import InterestScore, VideoSegment
from smartcut.video.scorers import (
    score_brightness_change,
    score_color_histogram_change,
    score_edge_variance,
    score_optical_flow,
)

logger = logging.getLogger(__name__)


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

        Reads and scores frames (GPU or CPU path), then derives scene boundaries
        from the color_change scores — no separate video pass needed.
        """
        frame_data = self._read_and_score()
        if not frame_data:
            return []

        boundaries = self._detect_boundaries_from_scores(frame_data)
        video_duration = frame_data[-1][0] + (1.0 / self.config.analysis_fps)
        segments = self._build_overlapping_windows(frame_data, video_duration, boundaries)
        return self._normalize_segments(segments)

    def _detect_boundaries_from_scores(
        self, frame_data: list[tuple[float, dict[str, float]]]
    ) -> list[float]:
        """Detect scene boundaries from existing color_change scores.

        Replaces the separate PySceneDetect pass by reusing the color histogram
        change already computed during frame scoring. This avoids reading the
        entire video a second time at full FPS.
        """
        threshold = self.config.scene_detect_threshold / 100.0
        boundaries = []
        for time, scores in frame_data:
            if scores.get("color_change", 0.0) > threshold:
                boundaries.append(time)
        return boundaries

    def _read_and_score(self) -> list[tuple[float, dict[str, float]]]:
        """Read sampled frames and score them.

        Selects GPU or CPU path based on config and hardware detection:
        - GPU path: accumulate all frames, batch-score edge/brightness/color on GPU,
          run optical flow on CPU in parallel, merge results.
        - CPU path (original): per-frame ThreadPoolExecutor scoring.
        """
        gpu_caps = detect_gpu()
        use_gpu = self.config.use_gpu and gpu_caps.cupy_available

        if use_gpu:
            return self._read_and_score_gpu()
        return self._read_and_score_cpu()

    def _get_video_info_ffprobe(self, ffmpeg_path: str) -> tuple[float, float] | None:
        """Get (fps, duration) via ffprobe. Returns None on failure."""
        ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v", "quiet",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=r_frame_rate,duration",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(self.config.video_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            # Parse FPS from r_frame_rate (e.g. "30000/1001")
            stream = data.get("streams", [{}])[0]
            rfr = stream.get("r_frame_rate", "")
            if "/" in rfr:
                num, den = rfr.split("/")
                fps = float(num) / float(den)
            elif rfr:
                fps = float(rfr)
            else:
                return None
            # Duration: prefer stream, fallback to format
            duration = float(stream.get("duration", 0))
            if duration <= 0:
                duration = float(data.get("format", {}).get("duration", 0))
            if duration <= 0:
                return None
            return (fps, duration)
        except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, json.JSONDecodeError):
            return None

    def _read_frames_nvdec(self) -> tuple[list[float], list[np.ndarray], list[np.ndarray]] | None:
        """Read frames using NVDEC hardware decoding via ffmpeg subprocess.

        Returns (times, grays, colors) or None on failure (triggering cv2 fallback).
        """
        gpu_caps = detect_gpu()
        if not gpu_caps.nvdec_available or not gpu_caps.system_ffmpeg:
            return None

        info = self._get_video_info_ffprobe(gpu_caps.system_ffmpeg)
        if info is None:
            return None
        fps, duration = info
        self.source_fps = fps

        analysis_fps = self.config.analysis_fps
        estimated_frames = int(duration * analysis_fps)
        frame_w, frame_h = 640, 360
        frame_bytes = frame_w * frame_h * 3

        cmd = [
            gpu_caps.system_ffmpeg,
            "-hwaccel", "cuda",
            "-i", str(self.config.video_path),
            "-vf", f"fps={analysis_fps},scale={frame_w}:{frame_h}",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-v", "quiet",
            "pipe:1",
        ]

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            return None

        times: list[float] = []
        grays: list[np.ndarray] = []
        colors: list[np.ndarray] = []
        frame_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task(
                "Reading video frames (NVDEC GPU decode)",
                total=estimated_frames,
            )
            while True:
                raw = proc.stdout.read(frame_bytes)
                if len(raw) < frame_bytes:
                    break
                frame = np.frombuffer(raw, dtype=np.uint8).reshape(frame_h, frame_w, 3).copy()
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                current_time = frame_count / analysis_fps
                times.append(current_time)
                grays.append(gray)
                colors.append(frame)
                frame_count += 1
                progress.update(task, completed=frame_count)
            progress.update(task, completed=max(estimated_frames, frame_count))

        proc.stdout.close()
        proc.wait()

        if not times:
            logger.warning("NVDEC produced 0 frames, falling back to cv2")
            return None

        logger.info("NVDEC decoded %d frames via hardware", len(times))
        return (times, grays, colors)

    def _read_frames_cv2(self) -> tuple[list[float], list[np.ndarray], list[np.ndarray]]:
        """Read frames using cv2.VideoCapture (CPU decode)."""
        cap = cv2.VideoCapture(str(self.config.video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.config.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        self.source_fps = fps or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(1, int(fps / self.config.analysis_fps))

        times: list[float] = []
        grays: list[np.ndarray] = []
        colors: list[np.ndarray] = []
        frame_idx = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task(
                "Reading video frames (CPU decode)",
                total=total_frames,
            )
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx % sample_interval == 0:
                    current_time = frame_idx / fps
                    frame_small = cv2.resize(frame, (640, 360))
                    gray_small = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)
                    times.append(current_time)
                    grays.append(gray_small)
                    colors.append(frame_small)
                frame_idx += 1
                progress.update(task, completed=frame_idx)
            progress.update(task, completed=total_frames)

        cap.release()
        return (times, grays, colors)

    def _read_and_score_gpu(self) -> list[tuple[float, dict[str, float]]]:
        """GPU scoring path: read all frames, then batch-score on GPU + CPU optical flow."""
        from smartcut.video.scorers_gpu import GPUFrameScorer

        # Phase 1: Read frames — try NVDEC first, fall back to cv2
        result = self._read_frames_nvdec()
        if result is not None:
            times, grays, colors = result
        else:
            times, grays, colors = self._read_frames_cv2()

        if not times:
            return []

        # Phase 2: GPU batch scoring + CPU optical flow in parallel
        gpu_scorer = GPUFrameScorer(batch_size=self.config.gpu_batch_size)
        num_workers = max(4, (os.cpu_count() or 4) - 2)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
        ) as progress:
            score_task = progress.add_task(
                "Scoring frames (GPU + CPU optical flow)",
                total=len(grays),
            )

            with ThreadPoolExecutor(max_workers=num_workers + 1) as executor:
                # Submit GPU batch scoring (runs on GPU, one thread is enough)
                gpu_future = executor.submit(gpu_scorer.score_batch, grays, colors)

                # Submit CPU optical flow for each frame pair
                flow_futures = {}
                for i in range(1, len(grays)):
                    f = executor.submit(score_optical_flow, grays[i - 1], grays[i])
                    flow_futures[i] = f

                # Collect GPU results
                gpu_results = gpu_future.result()
                progress.update(score_task, completed=len(grays) // 2)

                # Collect optical flow results
                flow_scores = {0: 0.0}
                for i, f in flow_futures.items():
                    flow_scores[i] = f.result()
                    progress.update(score_task, completed=len(grays) // 2 + i)

            progress.update(score_task, completed=len(grays))

        # Merge GPU + CPU results
        frame_data: list[tuple[float, dict[str, float]]] = []
        for i in range(len(times)):
            scores = dict(gpu_results[i])
            scores["optical_flow"] = flow_scores.get(i, 0.0)
            frame_data.append((times[i], scores))

        logger.info("GPU scoring complete: %d frames scored", len(frame_data))
        return frame_data

    def _read_and_score_cpu(self) -> list[tuple[float, dict[str, float]]]:
        """CPU scoring path (original): per-frame ThreadPoolExecutor scoring."""
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
