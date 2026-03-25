from __future__ import annotations

import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from trailvideocut.editor.assembler import _require_ffmpeg

console = Console()


class CharacterGridValidator:
    """Validate that a candidate plate region contains character-like contours.

    Uses adaptive thresholding to find dark-on-light character shapes, then
    checks count, size consistency, and horizontal alignment.
    """

    def __init__(
        self,
        min_char_count: int = 3,
        max_char_count: int = 10,
        min_char_height_ratio: float = 0.20,
        max_char_height_ratio: float = 0.85,
        min_char_width_ratio: float = 0.02,
        max_char_width_ratio: float = 0.25,
        alignment_tolerance: float = 0.35,
        height_consistency: float = 0.5,
    ):
        self._min_chars = min_char_count
        self._max_chars = max_char_count
        self._min_h_ratio = min_char_height_ratio
        self._max_h_ratio = max_char_height_ratio
        self._min_w_ratio = min_char_width_ratio
        self._max_w_ratio = max_char_width_ratio
        self._align_tol = alignment_tolerance
        self._h_consist = height_consistency

    def has_characters(
        self, gray: np.ndarray, bbox: tuple[int, int, int, int],
    ) -> bool:
        """Return True if the ROI at bbox contains a character-like pattern."""
        x1, y1, x2, y2 = bbox
        roi = gray[y1:y2, x1:x2]
        roi_h, roi_w = roi.shape[:2]
        if roi_h < 8 or roi_w < 15:
            return False

        char_bboxes = self._extract_character_contours(roi)
        return self._validate_character_set(char_bboxes, roi_h, roi_w)

    def _extract_character_contours(
        self, roi_gray: np.ndarray,
    ) -> list[tuple[int, int, int, int]]:
        """Find contours that could be individual characters in the ROI."""
        roi_h, roi_w = roi_gray.shape[:2]
        block = min(15, roi_w | 1, roi_h | 1)  # must be odd and <= dimensions
        if block < 3:
            return []
        binary = cv2.adaptiveThreshold(
            roi_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, blockSize=block, C=10,
        )
        contours, _ = cv2.findContours(
            binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        result = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w * h < 15:
                continue
            h_ratio = h / roi_h
            w_ratio = w / roi_w
            if not (self._min_h_ratio <= h_ratio <= self._max_h_ratio):
                continue
            if not (self._min_w_ratio <= w_ratio <= self._max_w_ratio):
                continue
            result.append((x, y, w, h))
        return result

    def _validate_character_set(
        self,
        char_bboxes: list[tuple[int, int, int, int]],
        roi_h: int,
        roi_w: int,
    ) -> bool:
        """Check count, size consistency, and horizontal alignment."""
        n = len(char_bboxes)
        if n < self._min_chars or n > self._max_chars:
            return False

        heights = np.array([h for _, _, _, h in char_bboxes], dtype=float)
        mean_h = float(np.mean(heights))
        if mean_h == 0:
            return False
        if float(np.std(heights)) / mean_h > self._h_consist:
            return False

        centers_y = np.array([y + h / 2 for _, y, _, h in char_bboxes], dtype=float)
        if float(np.std(centers_y)) / roi_h > self._align_tol:
            return False

        return True


class PlateShapeDetector:
    """Detect license plates by finding white rectangular regions.

    Pure OpenCV approach — no neural network. European plates are bright
    white rectangles that stand out against outdoor trail footage.
    Candidates are validated for character-like sub-contours to reduce
    false positives.
    """

    def __init__(self, validator: CharacterGridValidator | None = None):
        self._validator = validator or CharacterGridValidator()

    def detect(
        self, frame: np.ndarray,
    ) -> list[tuple[int, int, int, int]]:
        """Find white rectangular regions with plate-like aspect ratio.

        Global threshold to find white pixels, morphological closing to fill
        text gaps, then filter contours by aspect ratio, brightness, and contrast.
        Surviving candidates are validated for character-like content.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fh, fw = frame.shape[:2]

        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blur, 170, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

        candidates = self._find_plates(closed, gray, fh, fw, 1.2, 1.6, 300, 180)
        candidates = [c for c in candidates if not self._in_excluded_zone(c, fh, fw)]
        return [c for c in candidates if self._validator.has_characters(gray, c)]

    @staticmethod
    def _in_excluded_zone(
        bbox: tuple[int, int, int, int], fh: int, fw: int,
    ) -> bool:
        """Return True if bbox center falls in the bottom exclusion zone.

        Discards detections in the horizontal middle 60% AND bottom 30% of
        the frame — the region where the rider's dashboard and mirrors appear.
        """
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        in_middle_60_x = fw * 0.20 <= cx <= fw * 0.80
        in_bottom_30_y = cy >= fh * 0.70
        return in_middle_60_x and in_bottom_30_y

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

class PlateGapFiller:
    """Fill detection gaps with linearly interpolated positions.

    Short gaps (≤ *max_gap*) are interpolated immediately when the next
    detection arrives.  Longer gaps (up to *extended_gap*) are held in a
    pending buffer; if *confirm_after* consecutive detections follow, the
    gap is retroactively interpolated.  Gaps longer than *extended_gap*
    are emitted as empty.

    Results are emitted via :meth:`flush` as ``(plates, is_interpolated)``
    tuples.
    """

    _Entry = tuple[list[tuple[int, int, int, int]], bool]

    def __init__(
        self,
        detector: PlateShapeDetector,
        max_gap: int = 3,
        extended_gap: int = 15,
        max_distance: float = 150.0,
    ):
        self._detector = detector
        self._max_gap = max_gap
        self._extended_gap = extended_gap
        self._max_distance = max_distance

        self._prev: list[tuple[int, int, int, int]] = []
        self._resolved: deque[PlateGapFiller._Entry] = deque()
        self._pending: list[PlateGapFiller._Entry] = []
        self._gap_len = 0

        # Isolation filter: 1-entry lookahead
        self._held: PlateGapFiller._Entry | None = None
        self._last_emitted_plates: list[tuple[int, int, int, int]] = []

    def push(self, frame: np.ndarray) -> None:
        """Detect plates in *frame* and buffer the result."""
        plates = self._detector.detect(frame)

        if plates:
            if self._gap_len > 0 and self._prev:
                if self._gap_len <= self._max_gap and self._is_coherent(self._prev, plates):
                    # Short gap with coherent endpoints — interpolate
                    self._pending.append((plates, False))
                    self._interpolate_short_gap(plates)
                    self._resolve_pending()
                    self._prev = plates
                    self._gap_len = 0
                elif self._is_coherent(self._prev, plates):
                    # Long gap with coherent endpoints — interpolate
                    self._pending.append((plates, False))
                    self._interpolate_long_gap(plates)
                    self._resolve_pending()
                    self._prev = plates
                    self._gap_len = 0
                else:
                    # Incoherent detection mid-gap — don't break the gap.
                    # Include it in the buffer (isolation filter will strip
                    # it later if it's truly isolated), but keep the gap
                    # open looking for a coherent endpoint.
                    self._pending.append((plates, False))
                    self._gap_len += 1
                    if self._gap_len > self._extended_gap:
                        # Gap too long — give up on old _prev, start fresh
                        self._resolve_pending()
                        self._prev = plates
                        self._gap_len = 0
            else:
                # No gap or no prev — just resolve
                self._pending.append((plates, False))
                self._resolve_pending()
                # Only update _prev if coherent (or first detection).
                # Prevents isolated false positives from poisoning the
                # tracking state — the isolation filter will strip them
                # from the output, but _prev must stay clean.
                if not self._prev or self._is_coherent(self._prev, plates):
                    self._prev = plates
                self._gap_len = 0
        else:
            self._gap_len += 1
            self._pending.append(([], False))

            if self._gap_len > self._extended_gap:
                self._resolve_pending()
                self._prev = []
                self._gap_len = 0

    def flush(self) -> list[_Entry]:
        """Return resolved frames ready to be emitted."""
        result = list(self._resolved)
        self._resolved.clear()
        return result

    def flush_all(self) -> list[_Entry]:
        """Emit all remaining buffered frames (end of video)."""
        if self._gap_len > 0 and self._gap_len <= self._max_gap and self._prev:
            start = len(self._pending) - self._gap_len
            for i in range(self._gap_len):
                self._pending[start + i] = (self._prev, True)
        self._resolve_pending()
        self._flush_held()
        self._gap_len = 0
        self._prev = []
        return self.flush()

    def _resolve_pending(self) -> None:
        """Move all pending frames through the isolation filter to resolved."""
        for entry in self._pending:
            self._filter_and_emit(entry)
        self._pending.clear()

    def _filter_and_emit(self, entry: _Entry) -> None:
        """Emit the held entry (checking isolation) and hold the new one."""
        if self._held is not None:
            plates, is_interp = self._held
            if plates and not is_interp:
                # Real detection — check spatial coherence with neighbors
                backward_ok = self._is_coherent(plates, self._last_emitted_plates)
                forward_ok = self._is_coherent(plates, entry[0])
                if not backward_ok and not forward_ok:
                    # Isolated false positive — replace with interpolation
                    # from neighbors if both have plates, else strip.
                    fwd = entry[0]
                    bwd = self._last_emitted_plates
                    if bwd and fwd and self._is_coherent(bwd, fwd):
                        n = min(len(bwd), len(fwd))
                        interp = [self._lerp(bwd[pi], fwd[pi], 0.5) for pi in range(n)]
                        self._held = (interp, True)
                    else:
                        self._held = ([], False)
            held = self._held
            self._resolved.append(held)
            if held[0]:
                self._last_emitted_plates = held[0]
        self._held = entry

    def _flush_held(self) -> None:
        """Emit the last held entry (end of video — backward check only)."""
        if self._held is not None:
            plates, is_interp = self._held
            if plates and not is_interp:
                if not self._is_coherent(plates, self._last_emitted_plates):
                    self._held = ([], False)
            self._resolved.append(self._held)
            self._held = None

    def _is_coherent(
        self,
        plates_a: list[tuple[int, int, int, int]],
        plates_b: list[tuple[int, int, int, int]],
    ) -> bool:
        """Return True if any plate in a is near any plate in b."""
        if not plates_a or not plates_b:
            return False
        for a in plates_a:
            cx_a = (a[0] + a[2]) / 2
            cy_a = (a[1] + a[3]) / 2
            for b in plates_b:
                cx_b = (b[0] + b[2]) / 2
                cy_b = (b[1] + b[3]) / 2
                dist = ((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2) ** 0.5
                if dist <= self._max_distance:
                    return True
        return False

    def _interpolate_short_gap(
        self, next_plates: list[tuple[int, int, int, int]],
    ) -> None:
        """Interpolate the last ``_gap_len`` entries before the new detection."""
        n = min(len(self._prev), len(next_plates))
        total = self._gap_len + 1
        # Gap frames end just before the last entry (the new detection)
        gap_end = len(self._pending) - 1
        gap_start = gap_end - self._gap_len
        for gi in range(self._gap_len):
            t = (gi + 1) / total
            interp = [self._lerp(self._prev[pi], next_plates[pi], t) for pi in range(n)]
            self._pending[gap_start + gi] = (interp, True)

    def _interpolate_long_gap(
        self, next_plates: list[tuple[int, int, int, int]],
    ) -> None:
        """Interpolate an extended gap using _prev and next_plates as endpoints."""
        n = min(len(self._prev), len(next_plates))
        total = self._gap_len + 1
        gap_end = len(self._pending) - 1
        gap_start = gap_end - self._gap_len
        for gi in range(self._gap_len):
            t = (gi + 1) / total
            interp = [self._lerp(self._prev[pi], next_plates[pi], t) for pi in range(n)]
            self._pending[gap_start + gi] = (interp, True)

    @staticmethod
    def _lerp(
        a: tuple[int, int, int, int],
        b: tuple[int, int, int, int],
        t: float,
    ) -> tuple[int, int, int, int]:
        return (
            int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t),
            int(a[3] + (b[3] - a[3]) * t),
        )


class PlateBlurrer:
    """Detects and blurs license plates in a video file.

    Uses OpenCV shape detection to find white rectangular regions
    matching European plate proportions, then applies Gaussian blur.
    A gap-filler carries forward detections for brief dropouts.
    """

    def __init__(self, debug_dir: Path | None = None):
        self._gap_filler = PlateGapFiller(PlateShapeDetector())
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
            frame_buffer: deque[tuple[int, np.ndarray]] = deque()

            with Progress(
                TextColumn("  [cyan]Blurring plates"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("blur", total=total_frames or 1)
                debug_summary: list[str] = []
                emitted = 0

                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    self._gap_filler.push(frame)
                    frame_buffer.append((frame_idx, frame))
                    frame_idx += 1

                    for plates, is_interp in self._gap_filler.flush():
                        emit_idx, emit_frame = frame_buffer.popleft()
                        self._emit_frame(
                            emit_idx, emit_frame, plates, is_interp,
                            proc, debug_summary,
                        )
                        emitted += 1
                        progress.update(task, completed=emitted)
                        if progress_callback and total_frames > 0:
                            progress_callback(emitted, total_frames)

                # Flush remaining buffered frames at end of video
                for plates, is_interp in self._gap_filler.flush_all():
                    emit_idx, emit_frame = frame_buffer.popleft()
                    self._emit_frame(
                        emit_idx, emit_frame, plates, is_interp,
                        proc, debug_summary,
                    )
                    emitted += 1
                    progress.update(task, completed=emitted)
                    if progress_callback and total_frames > 0:
                        progress_callback(emitted, total_frames)

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

    def _emit_frame(
        self,
        frame_idx: int,
        frame: np.ndarray,
        plates: list[tuple[int, int, int, int]],
        is_interpolated: bool,
        proc: subprocess.Popen,
        debug_summary: list[str],
    ) -> None:
        """Blur plates, write to FFmpeg pipe, and optionally save debug."""
        if self._debug_dir:
            vis = frame.copy()
            color = (0, 255, 0) if is_interpolated else (0, 255, 255)
            for x1, y1, x2, y2 in plates:
                w, h = x2 - x1, y2 - y1
                label = f"{w}x{h} ~" if is_interpolated else f"{w}x{h}"
                cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    vis, label, (x1, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1,
                )
            cv2.imwrite(
                str(self._debug_dir / f"frame_{frame_idx:06d}.jpg"), vis,
            )
            box_strs = [f"({x1},{y1},{x2},{y2})" for x1, y1, x2, y2 in plates]
            tag = " (interpolated)" if is_interpolated else ""
            debug_summary.append(
                f"frame {frame_idx:06d}: {len(plates)} plates"
                + (f" [{' '.join(box_strs)}]" if box_strs else "")
                + tag
            )

        for bbox in plates:
            self.blur_region(frame, bbox)

        proc.stdin.write(frame.tobytes())

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
    """Run plate detection with gap-filling on every frame.

    Saves annotated debug images and a summary.  Interpolated detections
    are drawn in green (vs cyan for real detections) and tagged in the
    summary.
    """
    gap_filler = PlateGapFiller(PlateShapeDetector())

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_lines: list[str] = []
    frame_buffer: deque[tuple[int, np.ndarray]] = deque()
    frame_idx = 0

    def _emit(
        idx: int, frame: np.ndarray,
        plates: list[tuple[int, int, int, int]], is_interp: bool,
    ) -> None:
        color = (0, 255, 0) if is_interp else (0, 255, 255)
        vis = frame.copy()
        for x1, y1, x2, y2 in plates:
            w, h = x2 - x1, y2 - y1
            label = f"{w}x{h} ~" if is_interp else f"{w}x{h}"
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                vis, label, (x1, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1,
            )
        cv2.imwrite(str(output_dir / f"frame_{idx:06d}.jpg"), vis)
        box_strs = [f"({x1},{y1},{x2},{y2})" for x1, y1, x2, y2 in plates]
        tag = " (interpolated)" if is_interp else ""
        summary_lines.append(
            f"frame {idx:06d}: {len(plates)} plates"
            + (f" [{' '.join(box_strs)}]" if box_strs else "")
            + tag
        )

    with Progress(
        TextColumn("  [cyan]Detecting plates"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("detect", total=total_frames or 1)
        emitted = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            gap_filler.push(frame)
            frame_buffer.append((frame_idx, frame))
            frame_idx += 1

            for plates, is_interp in gap_filler.flush():
                eidx, eframe = frame_buffer.popleft()
                _emit(eidx, eframe, plates, is_interp)
                emitted += 1
                progress.update(task, completed=emitted)

        for plates, is_interp in gap_filler.flush_all():
            eidx, eframe = frame_buffer.popleft()
            _emit(eidx, eframe, plates, is_interp)
            emitted += 1
            progress.update(task, completed=emitted)

    cap.release()

    (output_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n")
    interp_count = sum(1 for l in summary_lines if "(interpolated)" in l)
    detect_count = sum(1 for l in summary_lines if "0 plates" not in l)
    console.print(
        f"  Done: {frame_idx} frames, "
        f"{detect_count} with detections ({interp_count} interpolated)"
    )
    console.print(f"  Output: {output_dir}")
