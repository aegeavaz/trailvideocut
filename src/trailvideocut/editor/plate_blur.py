from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from trailvideocut.editor.assembler import _require_ffmpeg

console = Console()


class PlateShapeDetector:
    """Detect license plates by finding white rectangular regions.

    Pure OpenCV approach — no neural network. European plates are bright
    white rectangles that stand out against outdoor trail footage.
    """

    def detect(
        self, frame: np.ndarray,
    ) -> list[tuple[int, int, int, int]]:
        """Find white rectangular regions with plate-like aspect ratio.

        Global threshold to find white pixels, morphological closing to fill
        text gaps, then filter contours by aspect ratio, brightness, and contrast.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fh, fw = frame.shape[:2]

        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blur, 170, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        return self._find_plates(closed, gray, fh, fw, 1.2, 1.6, 300, 180)

    @staticmethod
    def _find_plates(
        closed: np.ndarray,
        gray: np.ndarray,
        fh: int,
        fw: int,
        min_aspect: float,
        max_aspect: float,
        min_area: int,
        min_brightness: int = 180,
    ) -> list[tuple[int, int, int, int]]:
        frame_area = fw * fh
        contours, _ = cv2.findContours(
            closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        plates = []
        for cnt in contours:
            rect = cv2.minAreaRect(cnt)
            (cx, cy), (rw, rh), angle = rect
            if rw < rh:
                rw, rh = rh, rw
            if rh == 0:
                continue
            aspect = rw / rh
            area = rw * rh
            if not (min_aspect <= aspect <= max_aspect):
                continue
            if area < min_area or area > frame_area * 0.05:
                continue
            x1 = max(0, int(cx - rw / 2))
            y1 = max(0, int(cy - rh / 2))
            x2 = min(fw, int(cx + rw / 2))
            y2 = min(fh, int(cy + rh / 2))
            if x2 <= x1 or y2 <= y1:
                continue
            roi = gray[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            if float(np.mean(roi)) < min_brightness:
                continue
            if float(np.std(roi)) < 15:
                continue
            plates.append((x1, y1, x2, y2))
        return plates

class PlateBlurrer:
    """Detects and blurs license plates in a video file.

    Uses OpenCV shape detection to find white rectangular regions
    matching European plate proportions, then applies Gaussian blur.
    """

    def __init__(self, debug_dir: Path | None = None):
        self._detector = PlateShapeDetector()
        self._debug_dir = debug_dir
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)

    def blur_plates(
        self,
        input_path: str,
        output_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        """Read video, detect plates per frame, blur them, write output.

        Uses an FFmpeg pipe to write raw frames directly, encoding to H.264
        and copying audio from the original file in a single pass.
        Always writes to a temp file first, then replaces the output to avoid
        NTFS locking issues on WSL.
        """
        ffmpeg_bin = _require_ffmpeg()

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {input_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        out_dir = Path(output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp_fd = tempfile.NamedTemporaryFile(
            suffix=".mp4", dir=str(out_dir), delete=False,
        )
        actual_output = tmp_fd.name
        tmp_fd.close()

        cmd = [
            ffmpeg_bin, "-y",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-i", input_path,
            "-map", "0:v:0",
            "-map", "1:a:0?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-hide_banner",
            "-loglevel", "error",
            actual_output,
        ]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )

        try:
            frame_idx = 0

            with Progress(
                TextColumn("  [cyan]Blurring plates"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("blur", total=total_frames or 1)
                debug_summary: list[str] = []

                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    plates = self._detector.detect(frame)

                    if self._debug_dir:
                        vis = frame.copy()
                        for x1, y1, x2, y2 in plates:
                            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 255), 2)
                        cv2.imwrite(
                            str(self._debug_dir / f"frame_{frame_idx:06d}.jpg"), vis,
                        )
                        debug_summary.append(
                            f"frame {frame_idx:06d}: {len(plates)} plates"
                        )

                    for bbox in plates:
                        self.blur_region(frame, bbox)

                    proc.stdin.write(frame.tobytes())
                    frame_idx += 1

                    progress.update(task, completed=frame_idx)
                    if progress_callback and total_frames > 0:
                        progress_callback(frame_idx, total_frames)

                if self._debug_dir and debug_summary:
                    (self._debug_dir / "summary.txt").write_text(
                        "\n".join(debug_summary) + "\n"
                    )
                    console.print(
                        f"  Debug frames saved to {self._debug_dir}"
                    )
        finally:
            cap.release()
            if proc.stdin:
                proc.stdin.close()

        proc.wait()

        if proc.returncode != 0:
            Path(actual_output).unlink(missing_ok=True)
            stderr_text = (
                proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            )
            raise RuntimeError(
                f"FFmpeg plate blur failed (exit {proc.returncode}): "
                f"{stderr_text[-500:] or 'no stderr'}"
            )

        Path(actual_output).replace(output_path)

    @staticmethod
    def blur_region(
        frame: np.ndarray, bbox: tuple[int, int, int, int],
    ) -> np.ndarray:
        """Apply heavy Gaussian blur to a bounding box region."""
        x1, y1, x2, y2 = bbox
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return frame
        blurred = cv2.GaussianBlur(roi, (51, 51), 30)
        frame[y1:y2, x1:x2] = blurred
        return frame


def run_detection_debug(video_path: str, output_dir: Path) -> None:
    """Run plate shape detection on every frame, save annotated frames + summary.

    Pure OpenCV — finds white rectangular regions with plate-like aspect ratio.
    """
    detector = PlateShapeDetector()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_lines: list[str] = []
    frame_idx = 0

    with Progress(
        TextColumn("  [cyan]Detecting plates"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("detect", total=total_frames or 1)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            plates = detector.detect(frame)

            vis = frame.copy()
            for x1, y1, x2, y2 in plates:
                w, h = x2 - x1, y2 - y1
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 255), 2)
                cv2.putText(
                    vis, f"{w}x{h}", (x1, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1,
                )

            cv2.imwrite(str(output_dir / f"frame_{frame_idx:06d}.jpg"), vis)

            box_strs = [f"({x1},{y1},{x2},{y2})" for x1, y1, x2, y2 in plates]
            summary_lines.append(
                f"frame {frame_idx:06d}: {len(plates)} plates"
                + (f" [{' '.join(box_strs)}]" if box_strs else "")
            )

            frame_idx += 1
            progress.update(task, completed=frame_idx)

    cap.release()

    (output_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n")
    console.print(
        f"  Done: {frame_idx} frames, "
        f"{sum(1 for l in summary_lines if '0 plates' not in l)} with detections"
    )
    console.print(f"  Output: {output_dir}")
