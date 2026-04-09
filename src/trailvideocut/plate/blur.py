"""Plate blur processing for export and preview."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import cv2
import numpy as np

from trailvideocut.plate.models import ClipPlateData, PlateBox

if TYPE_CHECKING:
    from trailvideocut.plate.detector import PlateDetector

logger = logging.getLogger(__name__)


def calibrate_frame_offset(
    output_frame: np.ndarray,
    video_path: str | Path,
    expected_frame: int,
    search_range: int = 2,
) -> int:
    """Find the source frame that best matches *output_frame*.

    Compares *output_frame* (BGR) with source frames at
    ``expected_frame ± search_range`` using MSE on a center crop.
    Returns the offset from *expected_frame* (0 means exact match,
    -1 means the output frame matches source frame ``expected_frame - 1``,
    etc.).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0

    oh, ow = output_frame.shape[:2]
    # Use a center crop (1/4 of frame) for fast, reliable comparison
    cy, cx = oh // 4, ow // 4
    ch, cw = oh // 2, ow // 2
    out_crop = output_frame[cy:cy + ch, cx:cx + cw].astype(np.float32)

    best_offset = 0
    best_mse = float("inf")

    for offset in range(-search_range, search_range + 1):
        fn = expected_frame + offset
        if fn < 0:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, fn)
        ret, src_frame = cap.read()
        if not ret:
            continue
        sh, sw = src_frame.shape[:2]
        if sh != oh or sw != ow:
            continue
        src_crop = src_frame[cy:cy + ch, cx:cx + cw].astype(np.float32)
        mse = float(np.mean((out_crop - src_crop) ** 2))
        if mse < best_mse:
            best_mse = mse
            best_offset = offset

    cap.release()
    return best_offset


def expand_boxes_for_drift(
    detections: dict[int, list[PlateBox]],
    frame_num: int,
    margin_frames: int = 1,
) -> list[PlateBox]:
    """Return blur boxes expanded to cover plate positions in adjacent frames.

    For each box at *frame_num*, finds the closest box (by center distance)
    in frames ``frame_num ± 1..margin_frames`` and returns the bounding-box
    **union** of all matched positions.  This makes the blur robust to ±1
    frame timing drift — the expanded region covers the plate regardless of
    which adjacent frame the encoder/decoder actually shows.

    If *frame_num* has no detections, returns ``[]``.
    """
    boxes = detections.get(frame_num)
    if not boxes:
        return []

    result: list[PlateBox] = []
    for box in boxes:
        # Start with current box bounds
        x_min, y_min = box.x, box.y
        x_max = box.x + box.w
        y_max = box.y + box.h

        bcx = box.x + box.w / 2
        bcy = box.y + box.h / 2

        # Expand to cover adjacent frames' positions
        for offset in range(-margin_frames, margin_frames + 1):
            if offset == 0:
                continue
            adj_boxes = detections.get(frame_num + offset, [])
            # Find closest adjacent box by center distance
            best_dist = 0.1  # max match distance (normalized)
            best_adj = None
            for ab in adj_boxes:
                acx = ab.x + ab.w / 2
                acy = ab.y + ab.h / 2
                dist = ((bcx - acx) ** 2 + (bcy - acy) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_adj = ab
            if best_adj is not None:
                x_min = min(x_min, best_adj.x)
                y_min = min(y_min, best_adj.y)
                x_max = max(x_max, best_adj.x + best_adj.w)
                y_max = max(y_max, best_adj.y + best_adj.h)

        result.append(PlateBox(
            x=x_min,
            y=y_min,
            w=x_max - x_min,
            h=y_max - y_min,
            confidence=box.confidence,
            manual=box.manual,
            blur_strength=box.blur_strength,
        ))

    return result


def _blur_kernel_size(blur_strength: float, plate_px_w: int, plate_px_h: int) -> int:
    """Compute Gaussian kernel size from blur strength and plate pixel dimensions.

    Returns an odd integer >= 3, or 0 if blur_strength is effectively zero.
    """
    if blur_strength <= 0.0:
        return 0
    raw = int(blur_strength * min(plate_px_w, plate_px_h))
    k = max(3, raw)
    # Gaussian kernel must be odd
    if k % 2 == 0:
        k += 1
    return k


def apply_blur_to_frame(
    frame: np.ndarray,
    boxes: list[PlateBox],
    frame_h: int | None = None,
    frame_w: int | None = None,
) -> np.ndarray:
    """Apply Gaussian blur to plate regions on a single frame (in-place).

    Parameters
    ----------
    frame : np.ndarray
        BGR image (H, W, 3). Modified in-place and returned.
    boxes : list[PlateBox]
        Plate boxes with normalized coordinates and blur_strength.
    frame_h, frame_w : int, optional
        Override frame dimensions (defaults to frame.shape).

    Returns
    -------
    np.ndarray
        The same frame array with blur applied.
    """
    if frame_h is None:
        frame_h = frame.shape[0]
    if frame_w is None:
        frame_w = frame.shape[1]

    for box in boxes:
        if box.blur_strength <= 0.0:
            continue

        # Convert normalized coords to pixel coords, clamped to frame bounds
        x1 = max(0, int(box.x * frame_w))
        y1 = max(0, int(box.y * frame_h))
        x2 = min(frame_w, int((box.x + box.w) * frame_w))
        y2 = min(frame_h, int((box.y + box.h) * frame_h))

        pw = x2 - x1
        ph = y2 - y1
        if pw < 2 or ph < 2:
            continue

        k = _blur_kernel_size(box.blur_strength, pw, ph)
        if k < 3:
            continue

        frame[y1:y2, x1:x2] = cv2.GaussianBlur(
            frame[y1:y2, x1:x2], (k, k), 0
        )

    return frame


def grab_frame(
    video_path: str | Path,
    time_seconds: float,
    fps: float | None = None,
) -> np.ndarray | None:
    """Read a single frame from *video_path* at *time_seconds*.

    When *fps* is provided, seeks using ``CAP_PROP_POS_FRAMES`` with
    ``int(time_seconds * fps)`` to match the detector's frame indexing.
    Otherwise falls back to ``CAP_PROP_POS_MSEC``.

    Returns a BGR numpy array, or None on failure.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    try:
        if fps is not None:
            frame_num = int(time_seconds * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        else:
            cap.set(cv2.CAP_PROP_POS_MSEC, time_seconds * 1000.0)
        ret, frame = cap.read()
        if not ret:
            return None
        return frame
    finally:
        cap.release()


def _detect_near_stored(
    detector: PlateDetector,
    frame: np.ndarray,
    stored_boxes: list[PlateBox],
    crop_size: int = 320,
    model_size: int = 640,
) -> list[PlateBox]:
    """Re-detect plates by cropping around each stored position.

    For each non-manual stored box, extracts a *crop_size*×*crop_size*
    region centered on the stored position, upscales to
    *model_size*×*model_size*, and runs single-pass detection.

    Returns re-detected boxes in **full-frame normalized coordinates**,
    with ``blur_strength`` preserved from the matching stored box.
    Manual boxes are returned as-is (user positioned them intentionally).
    """
    fh, fw = frame.shape[:2]
    result: list[PlateBox] = []

    for sbox in stored_boxes:
        if sbox.manual:
            # Keep manual boxes with their stored coordinates
            result.append(sbox)
            continue

        cx = int((sbox.x + sbox.w / 2) * fw)
        cy = int((sbox.y + sbox.h / 2) * fh)

        half = crop_size // 2
        x0 = max(0, cx - half)
        y0 = max(0, cy - half)
        x1 = min(fw, x0 + crop_size)
        y1 = min(fh, y0 + crop_size)
        x0 = max(0, x1 - crop_size)
        y0 = max(0, y1 - crop_size)

        crop = frame[y0:y1, x0:x1]
        if crop.shape[0] < 10 or crop.shape[1] < 10:
            result.append(sbox)  # fallback
            continue

        upscaled = cv2.resize(crop, (model_size, model_size))
        fresh = detector.detect_frame(upscaled)

        # Map crop-space coords back to full-frame and find best match
        crop_w, crop_h = x1 - x0, y1 - y0
        best_box = None
        best_dist = 0.05
        scx = sbox.x + sbox.w / 2
        scy = sbox.y + sbox.h / 2

        for fb in fresh:
            fb_x = (fb.x * crop_w + x0) / fw
            fb_y = (fb.y * crop_h + y0) / fh
            fb_w = fb.w * crop_w / fw
            fb_h = fb.h * crop_h / fh
            fcx = fb_x + fb_w / 2
            fcy = fb_y + fb_h / 2
            dist = ((scx - fcx) ** 2 + (scy - fcy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_box = PlateBox(
                    x=fb_x, y=fb_y, w=fb_w, h=fb_h,
                    confidence=fb.confidence,
                    manual=False,
                    blur_strength=sbox.blur_strength,
                )

        result.append(best_box if best_box else sbox)

    return result


class PlateBlurProcessor:
    """Pre-processes a video segment by applying Gaussian blur to plate regions.

    Decodes frames via FFmpeg pipe and — when a *detector* is provided —
    re-detects plates on each frame to obtain coordinates that match
    the exact decode sequence.  This eliminates the spatial drift caused
    by two separate FFmpeg invocations producing subtly different frame
    content for HEVC video.
    """

    def __init__(
        self,
        video_path: str | Path,
        segment_start: float,
        segment_duration: float,
        clip_plate_data: ClipPlateData,
        fps: float,
        frame_width: int,
        frame_height: int,
        clip_index: int = -1,
        detector: "PlateDetector | None" = None,
        rational_fps: str = "",
    ):
        self._video_path = str(video_path)
        self._segment_start = segment_start
        self._segment_duration = segment_duration
        self._plate_data = clip_plate_data
        self._fps = fps
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._clip_index = clip_index
        self._detector = detector
        self._rational_fps = rational_fps or str(fps)

    def _get_boxes_for_frame(
        self,
        frame_num: int,
        det_keys: list[int],
    ) -> list[PlateBox]:
        """Look up detection boxes for *frame_num*.

        1. Exact match — returns boxes at that frame (auto-detected or manual).
        2. Outside detection range — returns boxes from the **nearest** frame
           key.  This handles crossfade-extended segments and respects any
           manual plates the user added beyond the original clip boundaries.
        3. Inside range but no entry — plate was not visible; returns ``[]``.
        """
        dets = self._plate_data.detections
        boxes = dets.get(frame_num)
        if boxes is not None:
            return boxes

        if not det_keys:
            return []

        # Frame is outside the detection range — extrapolate from nearest key
        if frame_num < det_keys[0] or frame_num > det_keys[-1]:
            import bisect
            idx = bisect.bisect_left(det_keys, frame_num)
            if idx == 0:
                nearest = det_keys[0]
            elif idx >= len(det_keys):
                nearest = det_keys[-1]
            else:
                before = det_keys[idx - 1]
                after = det_keys[idx]
                nearest = before if (frame_num - before) <= (after - frame_num) else after
            return dets.get(nearest, [])

        # Inside range, no detection at this frame — plate not visible
        return []

    def process_segment(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[Path, int]:
        """Read segment frames, blur plate regions, write to a temp file.

        Reads frames using **OpenCV** ``CAP_PROP_POS_FRAMES`` seeking —
        the same method that ``grab_frame()`` and the blur preview use.
        This guarantees that the blur processor sees the exact same frame
        content as the preview, so manual plate positions match exactly.

        Returns ``(path, frames_written)``.
        """
        from trailvideocut.gpu import _find_ffmpeg

        ffmpeg_bin = _find_ffmpeg()
        if ffmpeg_bin is None:
            raise RuntimeError("FFmpeg not found for blur pre-processing")

        seg_start_frame = int(self._segment_start * self._fps)
        seg_end_frame = int(
            (self._segment_start + self._segment_duration) * self._fps,
        )

        det_keys = sorted(self._plate_data.detections.keys())
        det_min = det_keys[0] if det_keys else seg_start_frame
        det_max = det_keys[-1] if det_keys else seg_start_frame

        print(
            f"  [blur] clip={self._clip_index} "
            f"seg_start={self._segment_start:.6f}s "
            f"fps={self._fps:.4f} "
            f"seg_frames={seg_start_frame}-{seg_end_frame} "
            f"det_range={det_min}-{det_max} "
            f"decoder=opencv"
        )

        # Write blurred frames as raw YUV420P (no container, no timestamps).
        tmp = tempfile.NamedTemporaryFile(
            suffix=".yuv", prefix="plate_blur_", delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.close()

        # Read frames with OpenCV (same as grab_frame / blur preview)
        cap = cv2.VideoCapture(self._video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self._video_path}")

        try:
            frames_written = 0
            total_seg_frames = max(1, seg_end_frame - seg_start_frame)

            cap.set(cv2.CAP_PROP_POS_FRAMES, seg_start_frame)

            with open(tmp_path, "wb") as raw_out:
                for abs_frame in range(seg_start_frame, seg_end_frame):
                    ret, frame = cap.read()
                    if not ret:
                        break

                    boxes = self._get_boxes_for_frame(abs_frame, det_keys)

                    if boxes:
                        apply_blur_to_frame(
                            frame, boxes, self._frame_height, self._frame_width,
                        )

                    yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
                    raw_out.write(yuv.tobytes())
                    frames_written += 1

                    if progress_callback and (frames_written % 10 == 0):
                        progress_callback(frames_written, total_seg_frames)

            if progress_callback:
                progress_callback(frames_written, frames_written)
        finally:
            cap.release()

        return tmp_path, frames_written

