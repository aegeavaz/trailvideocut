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


def _box_corners_unit(box: PlateBox) -> np.ndarray:
    """Return the four corners of *box* in normalized (0-1) coordinates.

    For axis-aligned boxes the corners are the rectangle's corners; for
    oriented boxes they are the rotated-rectangle corners.
    """
    corners = box.corners_px(1.0, 1.0)
    return np.array(corners, dtype=np.float64)


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

    If any source or matched-neighbour box is oriented (``angle != 0``),
    the union is computed as the tightest oriented rectangle enclosing all
    corner points (``cv2.minAreaRect`` over the corner cloud). Otherwise the
    axis-aligned bounding box of the participants is returned unchanged.

    If *frame_num* has no detections, returns ``[]``.
    """
    boxes = detections.get(frame_num)
    if not boxes:
        return []

    result: list[PlateBox] = []
    for box in boxes:
        participants: list[PlateBox] = [box]

        bcx = box.x + box.w / 2
        bcy = box.y + box.h / 2

        # Collect closest matching box from each adjacent frame.
        for offset in range(-margin_frames, margin_frames + 1):
            if offset == 0:
                continue
            adj_boxes = detections.get(frame_num + offset, [])
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
                participants.append(best_adj)

        any_oriented = any(p.angle != 0.0 for p in participants)

        if not any_oriented:
            # Legacy path — axis-aligned union, pixel-identical to v1 behaviour.
            x_min = min(p.x for p in participants)
            y_min = min(p.y for p in participants)
            x_max = max(p.x + p.w for p in participants)
            y_max = max(p.y + p.h for p in participants)
            result.append(PlateBox(
                x=x_min,
                y=y_min,
                w=x_max - x_min,
                h=y_max - y_min,
                confidence=box.confidence,
                manual=box.manual,
            ))
        else:
            # Oriented union — tightest rotated rect over all corners.
            all_corners = np.vstack([_box_corners_unit(p) for p in participants])
            (cx, cy), (w, h), angle = cv2.minAreaRect(
                all_corners.astype(np.float32),
            )
            if w < h:
                w, h = h, w
                angle += 90.0
            # Normalize angle into (-45, 45].
            angle = ((angle + 45.0) % 90.0) - 45.0
            result.append(PlateBox(
                x=cx - w / 2.0,
                y=cy - h / 2.0,
                w=w,
                h=h,
                confidence=box.confidence,
                manual=box.manual,
                angle=angle,
            ))

    return result


def _blur_kernel_size(plate_px_w: int, plate_px_h: int) -> int:
    """Compute Gaussian kernel size from plate pixel dimensions.

    Returns an odd integer >= 3.  Larger plates get a proportionally
    larger kernel so the blur fully obscures the content.
    """
    k = max(3, min(plate_px_w, plate_px_h))
    # Gaussian kernel must be odd
    if k % 2 == 0:
        k += 1
    return k


def _apply_aabb_blur(
    frame: np.ndarray, box: PlateBox, frame_h: int, frame_w: int,
) -> None:
    """Apply Gaussian blur to an axis-aligned box (in-place on *frame*).

    Preserves the pre-refinement pixel behaviour exactly.
    """
    x1 = max(0, int(box.x * frame_w))
    y1 = max(0, int(box.y * frame_h))
    x2 = min(frame_w, int((box.x + box.w) * frame_w))
    y2 = min(frame_h, int((box.y + box.h) * frame_h))

    pw = x2 - x1
    ph = y2 - y1
    if pw < 2 or ph < 2:
        return

    k = _blur_kernel_size(pw, ph)
    frame[y1:y2, x1:x2] = cv2.GaussianBlur(frame[y1:y2, x1:x2], (k, k), 0)


def _apply_oriented_blur(
    frame: np.ndarray, box: PlateBox, frame_h: int, frame_w: int,
) -> None:
    """Apply Gaussian blur to an oriented (rotated-rectangle) box in-place.

    The blur is applied through a polygon mask so that pixels inside the
    rotated quadrilateral are blurred while pixels inside the box's AABB
    envelope but outside the quadrilateral stay untouched. Kernel size is
    derived from the rotated rectangle's own ``(w, h)`` — *not* the envelope.
    """
    # Work inside the axis-aligned envelope to keep the cost localised.
    env_x, env_y, env_w, env_h = box.aabb_envelope()
    x1 = max(0, int(env_x * frame_w))
    y1 = max(0, int(env_y * frame_h))
    x2 = min(frame_w, int((env_x + env_w) * frame_w))
    y2 = min(frame_h, int((env_y + env_h) * frame_h))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return

    # Kernel is derived from the plate-aligned (rotated) extents so the blur
    # strength matches an equivalent axis-aligned plate of the same physical
    # size.
    plate_px_w = max(1, int(round(box.w * frame_w)))
    plate_px_h = max(1, int(round(box.h * frame_h)))
    k = _blur_kernel_size(plate_px_w, plate_px_h)

    # Polygon corners in envelope-local pixel coordinates.
    corners = box.corners_px(frame_w, frame_h)
    local = np.array(
        [[round(cx - x1), round(cy - y1)] for cx, cy in corners],
        dtype=np.int32,
    )

    patch = frame[y1:y2, x1:x2]
    blurred = cv2.GaussianBlur(patch, (k, k), 0)
    mask = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, local, 255)
    # Copy blurred pixels only where the mask covers the rotated rectangle.
    np.copyto(patch, blurred, where=mask[..., None].astype(bool))


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
        Plate boxes with normalized coordinates. Boxes with a non-zero
        ``angle`` are blurred through a rotated-rectangle mask; boxes with
        ``angle == 0`` go through the legacy axis-aligned path unchanged.
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
        if box.angle == 0.0:
            _apply_aabb_blur(frame, box, frame_h, frame_w)
        else:
            _apply_oriented_blur(frame, box, frame_h, frame_w)

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

    Returns re-detected boxes in **full-frame normalized coordinates**.
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
                )

        result.append(best_box if best_box else sbox)

    return result


def _find_first_keyframe(
    video_path: str | Path,
    start_frame: int,
    end_frame: int,
    fps: float = 0,
) -> int | None:
    """Find the first keyframe in ``[start_frame, end_frame)``.

    Tries ffprobe first (fast packet scan), falls back to ffmpeg
    ``-vf showinfo`` (works with imageio-ffmpeg on Windows).

    Returns the **absolute** frame number of the first keyframe, or
    ``None`` on failure.
    """
    import subprocess

    # --- Attempt 1: ffprobe (fast, no decoding) ---
    from trailvideocut.gpu import _find_ffprobe
    ffprobe_bin = _find_ffprobe()
    if ffprobe_bin is not None:
        try:
            result = subprocess.run(
                [
                    ffprobe_bin, "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "packet=pts,flags",
                    "-of", "csv=p=0",
                    str(video_path),
                ],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                frame_idx = 0
                for line in result.stdout.splitlines():
                    if frame_idx >= end_frame:
                        break
                    parts = line.strip().split(",")
                    if len(parts) >= 2 and "K" in parts[-1]:
                        if frame_idx >= start_frame:
                            return frame_idx
                    frame_idx += 1
        except (subprocess.TimeoutExpired, OSError):
            pass  # fall through to ffmpeg

    # --- Attempt 2: ffmpeg -vf showinfo (works without ffprobe) ---
    from trailvideocut.gpu import _find_ffmpeg
    ffmpeg_bin = _find_ffmpeg()
    if ffmpeg_bin is None or fps <= 0:
        return None

    # Seek a bit before the segment and scan ~5 seconds
    seek_time = max(0, start_frame / fps - 0.5)
    scan_dur = (end_frame - start_frame) / fps + 1.0
    try:
        result = subprocess.run(
            [
                ffmpeg_bin, "-hide_banner",
                "-ss", f"{seek_time:.6f}",
                "-i", str(video_path),
                "-t", f"{scan_dur:.6f}",
                "-vf", "showinfo",
                "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    # Parse showinfo output from stderr: lines contain n:N and iskey:1
    import re
    for line in result.stderr.splitlines():
        if "iskey:1" not in line:
            continue
        m = re.search(r"\bn:\s*(\d+)\b", line)
        pts_m = re.search(r"\bpts_time:\s*([\d.]+)", line)
        if m and pts_m:
            # Convert pts_time to absolute frame number
            pts_time = float(pts_m.group(1))
            abs_frame = int((seek_time + pts_time) * fps)
            if start_frame <= abs_frame < end_frame:
                return abs_frame

    return None


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
        2. Outside detection range or inside range with no entry — plate was
           not visible; returns ``[]``.
        """
        dets = self._plate_data.detections
        boxes = dets.get(frame_num)
        if boxes is not None:
            return boxes

        return []

    @staticmethod
    def _nearest_boxes(
        detections: dict[int, list[PlateBox]],
        frame_num: int,
        window: int = 2,
    ) -> list[PlateBox]:
        """Return boxes from the nearest frame within ±*window*.

        Same logic as the DaVinci Lua script's ``_nearest_box_for_frame``:
        exact match first, then ±1, ±2, etc.  Returns the **original**
        boxes (no expansion), so the blur region is precise.
        """
        boxes = detections.get(frame_num)
        if boxes is not None:
            return boxes
        for offset in range(1, window + 1):
            prev = detections.get(frame_num - offset)
            if prev is not None:
                return prev
            nxt = detections.get(frame_num + offset)
            if nxt is not None:
                return nxt
        return []

    def process_segment(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[Path, int]:
        """Read segment frames, blur plate regions, write to a temp file.

        Blur boxes for the frame at source-video index ``abs_frame`` are
        looked up using ``abs_frame`` itself as the key — the same integer
        key the detector writes into ``ClipPlateData.detections``. Falls
        back to nearest-neighbour lookup within ±2 frames for precise box
        matching when an exact key is missing.

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

        logger.info(
            "blur clip=%d seg=%d-%d det=%d-%d",
            self._clip_index, seg_start_frame, seg_end_frame,
            det_min, det_max,
        )

        # Read frames with OpenCV (same as grab_frame / blur preview)
        cap = cv2.VideoCapture(self._video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self._video_path}")

        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, seg_start_frame)

            # Write blurred frames as raw YUV420P
            tmp = tempfile.NamedTemporaryFile(
                suffix=".yuv", prefix="plate_blur_", delete=False,
            )
            tmp_path = Path(tmp.name)
            tmp.close()

            frames_written = 0
            total_seg_frames = max(1, seg_end_frame - seg_start_frame)
            dets = self._plate_data.detections

            with open(tmp_path, "wb") as raw_out:
                for abs_frame in range(seg_start_frame, seg_end_frame):
                    ret, frame = cap.read()
                    if not ret:
                        break

                    lookup_frame = abs_frame

                    boxes = self._nearest_boxes(dets, lookup_frame)
                    if not boxes:
                        boxes = self._get_boxes_for_frame(
                            lookup_frame, det_keys,
                        )

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

