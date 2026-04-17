"""License plate detector with tiling for small plates.

Backend priority (GPU-aware): ultralytics+CUDA > onnxruntime+CUDA > onnxruntime+DirectML > ultralytics CPU > onnxruntime CPU > cv2.dnn
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from trailvideocut.plate.models import ClipPlateData, PlateBox

# Detect available backends and their GPU capability
_HAS_ULTRALYTICS = False
_HAS_ORT = False
_TORCH_CUDA = False
_ORT_CUDA = False
_ORT_DML = False

try:
    from ultralytics import YOLO
    _HAS_ULTRALYTICS = True
    import torch
    _TORCH_CUDA = torch.cuda.is_available()
except ImportError:
    pass

try:
    import onnxruntime as ort
    _HAS_ORT = True
    try:
        _available_providers = ort.get_available_providers()
        _ORT_CUDA = "CUDAExecutionProvider" in _available_providers
        _ORT_DML = "DmlExecutionProvider" in _available_providers
    except AttributeError:
        pass
except ImportError:
    pass

# Prefer GPU-capable backend over CPU-only
if _HAS_ULTRALYTICS and _TORCH_CUDA:
    _BACKEND = "ultralytics"
elif _HAS_ORT and (_ORT_CUDA or _ORT_DML):
    _BACKEND = "onnxruntime"
elif _HAS_ULTRALYTICS:
    _BACKEND = "ultralytics"
elif _HAS_ORT:
    _BACKEND = "onnxruntime"
else:
    _BACKEND = "cv2"


class PlateDetector:
    """Detects license plates in video frames using a YOLO ONNX model."""

    INPUT_SIZE = 640

    # Tiling constants
    TILE_CROP = 320   # crop size from original frame
    TILE_STRIDE = 160  # stride (50% overlap)

    # Plate geometry filters (applied after detection)
    MIN_PLATE_PX_W = 10   # minimum width in pixels
    MIN_PLATE_PX_H = 5    # minimum height in pixels
    PLATE_ASPECT_MIN = 0.5  # min width/height ratio (motorcycle plates can be ~1.2-1.4)
    PLATE_ASPECT_MAX = 2.0  # max width/height ratio

    # "Dashboard" exclusion: masks the user's own bike / mounted phone area at
    # the bottom of the frame. COCO 'cell phone' (class 67) is unreliable for
    # dashboard-mounted GPS phones — yolov8n misclassifies them as 'cup', etc.
    # Empirically YOLO consistently classifies the dashboard region as a
    # motorcycle (class 3), so we use that class and a position/area filter
    # (bottom of frame, large area) to distinguish the user's own bike from
    # other riders in the scene.
    _PHONE_CLASSES = {3}           # COCO class IDs: 3 = "motorcycle"
    _PHONE_CONF = 0.20             # min class-score for candidate detections
    _PHONE_MIN_BOTTOM_FRAC = 0.85  # detection bottom-edge must be this far down
    _PHONE_MIN_AREA_FRAC = 0.04    # detection must cover this fraction of the frame
    _PHONE_PAD = 0.2               # pad the zone by 20% on each side
    _PHONE_REDETECT_EVERY = 30     # re-run detection every N frames

    def __init__(
        self,
        model_path: str | Path,
        confidence_threshold: float = 0.05,
        exclude_phones: bool = False,
        phone_redetect_every: int = _PHONE_REDETECT_EVERY,
        verbose: bool = False,
        min_ratio: float = 0.5,
        max_ratio: float = 2.0,
        min_plate_px_w: int = 10,
        min_plate_px_h: int = 5,
    ):
        self._threshold = confidence_threshold
        self._model_path = str(model_path)
        self._has_cuda = False
        self._exclude_phones = exclude_phones
        self._phone_redetect_every = max(1, phone_redetect_every)
        self._verbose = verbose
        self._min_ratio = min_ratio
        self._max_ratio = max_ratio
        self._min_plate_px_w = min_plate_px_w
        self._min_plate_px_h = min_plate_px_h
        self._phone_zones: list[tuple[float, float, float, float]] = []
        self._phone_ort_session = None  # onnxruntime.InferenceSession | None
        self._phone_model_loaded: bool = False
        self._phone_frame_counter = 0
        self._current_frame_num: int = -1  # for verbose logging context
        self._frame_header_printed: bool = False

        if _BACKEND == "ultralytics":
            self._model = YOLO(self._model_path, task="detect")
            import torch
            self._has_cuda = torch.cuda.is_available()
            device = "cuda" if self._has_cuda else "cpu"
            # Warm up model on the target device
            self._device = device
            if self._verbose:
                print(f"[PlateDetect] Backend: ultralytics/PyTorch ({device})")
        elif _BACKEND == "onnxruntime":
            providers = []
            try:
                available = ort.get_available_providers()
            except AttributeError:
                available = ["CPUExecutionProvider"]
            self._has_cuda = "CUDAExecutionProvider" in available
            has_dml = "DmlExecutionProvider" in available
            if self._has_cuda:
                providers.append("CUDAExecutionProvider")
            if has_dml:
                providers.append("DmlExecutionProvider")
            providers.append("CPUExecutionProvider")
            self._session = ort.InferenceSession(
                self._model_path, providers=providers,
            )
            self._input_name = self._session.get_inputs()[0].name
            active = self._session.get_providers()
            if "CUDAExecutionProvider" in active:
                gpu_label = "CUDA"
            elif "DmlExecutionProvider" in active:
                gpu_label = "DirectML"
            else:
                gpu_label = "CPU"
            if self._verbose:
                print(f"[PlateDetect] Backend: onnxruntime ({gpu_label})")
        else:
            self._net = cv2.dnn.readNetFromONNX(self._model_path)
            if self._verbose:
                print("[PlateDetect] Backend: cv2.dnn (CPU)")

    @property
    def backend(self) -> str:
        return _BACKEND

    def detect_frame(self, frame: np.ndarray) -> list[PlateBox]:
        """Run single-pass detection on a BGR frame (full frame -> 640x640)."""
        h, w = frame.shape[:2]
        self.update_phone_zones(frame)

        if _BACKEND == "ultralytics":
            boxes = self._detect_ultralytics(frame)
        else:
            letterboxed, ratio, (pad_w, pad_h) = self._letterbox(frame)
            if _BACKEND == "onnxruntime":
                outputs = self._infer_ort(letterboxed)
            else:
                outputs = self._infer_cv2(letterboxed)
            boxes = self._parse_output(outputs, w, h, ratio, pad_w, pad_h)

        boxes = self._filter_geometry(boxes, w, h)
        return self._filter_phone_zones(boxes)

    def detect_frame_tiled(self, frame: np.ndarray) -> list[PlateBox]:
        """Tiled detection for small plates: 320x320 crops -> 640x640 upscale -> detect."""
        h, w = frame.shape[:2]
        self.update_phone_zones(frame)
        tiles = []
        tile_coords = []

        for ty in range(0, h - self.TILE_CROP + 1, self.TILE_STRIDE):
            for tx in range(0, w - self.TILE_CROP + 1, self.TILE_STRIDE):
                crop = frame[ty:ty + self.TILE_CROP, tx:tx + self.TILE_CROP]
                tiles.append(crop)
                tile_coords.append((tx, ty))

        # Edge tiles if frame isn't evenly divisible
        last_tx = w - self.TILE_CROP
        last_ty = h - self.TILE_CROP
        for ty in range(0, h - self.TILE_CROP + 1, self.TILE_STRIDE):
            if last_tx % self.TILE_STRIDE != 0:
                crop = frame[ty:ty + self.TILE_CROP, last_tx:last_tx + self.TILE_CROP]
                tiles.append(crop)
                tile_coords.append((last_tx, ty))
        for tx in range(0, w - self.TILE_CROP + 1, self.TILE_STRIDE):
            if last_ty % self.TILE_STRIDE != 0:
                crop = frame[last_ty:last_ty + self.TILE_CROP, tx:tx + self.TILE_CROP]
                tiles.append(crop)
                tile_coords.append((tx, last_ty))

        if not tiles:
            return []

        all_boxes: list[PlateBox] = []
        for tile, (tx, ty) in zip(tiles, tile_coords):
            upscaled = cv2.resize(tile, (self.INPUT_SIZE, self.INPUT_SIZE))

            if _BACKEND == "ultralytics":
                boxes = self._detect_ultralytics(upscaled)
            elif _BACKEND == "onnxruntime":
                outputs = self._infer_ort(upscaled)
                boxes = self._parse_output(outputs, self.INPUT_SIZE, self.INPUT_SIZE)
            else:
                outputs = self._infer_cv2(upscaled)
                boxes = self._parse_output(outputs, self.INPUT_SIZE, self.INPUT_SIZE)

            # Map tile-space coords back to original frame
            for box in boxes:
                box.x = (box.x * self.TILE_CROP + tx) / w
                box.y = (box.y * self.TILE_CROP + ty) / h
                box.w = box.w * self.TILE_CROP / w
                box.h = box.h * self.TILE_CROP / h

            all_boxes.extend(boxes)

        if len(all_boxes) > 1:
            all_boxes = self._nms(all_boxes, iou_threshold=0.5)

        all_boxes = self._filter_geometry(all_boxes, w, h)
        return self._filter_phone_zones(all_boxes)

    # --- Post-detection filters ---

    def _filter_geometry(
        self, boxes: list[PlateBox], frame_w: int, frame_h: int,
    ) -> list[PlateBox]:
        """Remove detections that don't match license plate geometry."""
        filtered = []
        for box in boxes:
            w_px = box.w * frame_w
            h_px = box.h * frame_h
            aspect = w_px / h_px if h_px > 0 else 0
            x_px = int(box.x * frame_w)
            y_px = int(box.y * frame_h)
            if w_px < self._min_plate_px_w or h_px < self._min_plate_px_h:
                if self._verbose:
                    self._print_frame_header()
                    print(f"[PlateDetect]   FILTERED (too small) | "
                          f"pos: ({x_px}, {y_px}) px | "
                          f"size: {w_px:.0f}x{h_px:.0f} px | "
                          f"aspect: {aspect:.2f} | "
                          f"confidence: {box.confidence:.1%}")
                continue
            if aspect < self._min_ratio or aspect > self._max_ratio:
                if self._verbose:
                    self._print_frame_header()
                    print(f"[PlateDetect]   FILTERED (bad aspect) | "
                          f"pos: ({x_px}, {y_px}) px | "
                          f"size: {w_px:.0f}x{h_px:.0f} px | "
                          f"aspect: {aspect:.2f} | "
                          f"confidence: {box.confidence:.1%}")
                continue
            if self._verbose:
                self._print_frame_header()
                print(f"[PlateDetect]   KEPT               | "
                      f"pos: ({x_px}, {y_px}) px | "
                      f"size: {w_px:.0f}x{h_px:.0f} px | "
                      f"aspect: {aspect:.2f} | "
                      f"confidence: {box.confidence:.1%}")
            filtered.append(box)
        return filtered

    def _print_frame_header(self):
        """Print frame header once per frame when verbose."""
        if not self._frame_header_printed:
            print(f"[PlateDetect] Frame {self._current_frame_num}:")
            self._frame_header_printed = True

    # --- Phone / device exclusion ---

    def _ensure_phone_model(self) -> None:
        """Lazily load the bundled YOLOv8n COCO ONNX model for phone detection.

        Runs under onnxruntime only — same stack the plate model uses on
        DirectML / CUDA / CPU. Silent no-op if onnxruntime is unavailable or
        the bundled ``resources/yolov8n.onnx`` file is missing.
        """
        if self._phone_model_loaded:
            return
        self._phone_model_loaded = True

        if not _HAS_ORT:
            if self._verbose:
                print(
                    "[PlateDetect] Phone filtering disabled: onnxruntime is "
                    "not installed.",
                )
            return

        from trailvideocut.plate.model_manager import get_coco_model_path
        coco_path = get_coco_model_path()
        if coco_path is None:
            if self._verbose:
                print(
                    "[PlateDetect] Phone filtering disabled: "
                    "resources/yolov8n.onnx missing from install.",
                )
            return

        try:
            providers = []
            available = ort.get_available_providers()
            if "CUDAExecutionProvider" in available:
                providers.append("CUDAExecutionProvider")
            if "DmlExecutionProvider" in available:
                providers.append("DmlExecutionProvider")
            providers.append("CPUExecutionProvider")
            self._phone_ort_session = ort.InferenceSession(
                str(coco_path), providers=providers,
            )
            if self._verbose:
                active = self._phone_ort_session.get_providers()
                print(f"[PlateDetect] Phone backend: onnxruntime ({active[0]})")
        except Exception as exc:
            if self._verbose:
                print(f"[PlateDetect] Failed to load phone ONNX model: {exc}")
            self._phone_ort_session = None

    def detect_phones(self, frame: np.ndarray) -> list[tuple[float, float, float, float]]:
        """Detect phones/devices in frame. Returns list of padded (x, y, w, h) normalized zones."""
        self._ensure_phone_model()
        if self._phone_ort_session is None:
            return []
        return self._detect_phones_ort(frame)

    def _detect_phones_ort(
        self, frame: np.ndarray,
    ) -> list[tuple[float, float, float, float]]:
        """Run the bundled YOLOv8n COCO ONNX model and return dashboard zones.

        Output tensor shape is ``(1, 84, 8400)``: channels 0-3 are
        ``cx, cy, w, h`` in input (letterboxed) pixel space, and channels
        4-83 are the 80 COCO class scores (sigmoid already applied). We
        keep anchors whose argmax class is in ``_PHONE_CLASSES`` (currently
        motorcycle). Then we filter by bottom-of-frame position and area so
        only the user's own bike/dashboard is retained, not other riders.
        """
        h, w = frame.shape[:2]
        letterboxed, ratio, (pad_w, pad_h) = self._letterbox(frame)
        blob = letterboxed.astype(np.float32) / 255.0
        blob = blob[:, :, ::-1]  # BGR -> RGB
        blob = blob.transpose(2, 0, 1)[np.newaxis]
        blob = np.ascontiguousarray(blob)
        input_name = self._phone_ort_session.get_inputs()[0].name
        outputs = self._phone_ort_session.run(None, {input_name: blob})[0]

        preds = outputs[0]  # (84, 8400)
        class_scores = preds[4:]                    # (80, 8400)
        top_cls = class_scores.argmax(axis=0)       # (8400,)
        top_conf = class_scores.max(axis=0)         # (8400,)

        cls_mask = np.isin(top_cls, list(self._PHONE_CLASSES))
        conf_mask = top_conf >= self._PHONE_CONF
        keep_mask = cls_mask & conf_mask
        if not keep_mask.any():
            return []

        cxs = preds[0, keep_mask]
        cys = preds[1, keep_mask]
        ws = preds[2, keep_mask]
        hs = preds[3, keep_mask]
        confs = top_conf[keep_mask]

        boxes_px = np.stack(
            [cxs - ws / 2, cys - hs / 2, cxs + ws / 2, cys + hs / 2],
            axis=1,
        )
        keep = self._nms_xyxy(boxes_px, confs, iou_threshold=0.5)

        raw_boxes: list[tuple[float, float, float, float]] = []
        for i in keep:
            x1p, y1p, x2p, y2p = boxes_px[i]
            # Undo letterboxing back to original-image coordinates
            x1 = (x1p - pad_w) / ratio
            y1 = (y1p - pad_h) / ratio
            x2 = (x2p - pad_w) / ratio
            y2 = (y2p - pad_h) / ratio
            # Reject anything that isn't near the bottom + large enough to be
            # the user's own bike rather than another rider.
            bottom_frac = y2 / h
            area_frac = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1)) / max(1, w * h)
            if bottom_frac < self._PHONE_MIN_BOTTOM_FRAC:
                continue
            if area_frac < self._PHONE_MIN_AREA_FRAC:
                continue
            raw_boxes.append((x1, y1, x2, y2))

        # Merge overlapping survivors into their union bounding box so the
        # overlay shows one clean zone per dashboard rather than nested
        # rectangles. Filtering semantics (union) are preserved.
        merged = self._merge_overlapping_boxes(raw_boxes)
        return [
            self._pad_phone_zone(x1, y1, x2 - x1, y2 - y1, w, h)
            for x1, y1, x2, y2 in merged
        ]

    @staticmethod
    def _merge_overlapping_boxes(
        boxes: list[tuple[float, float, float, float]],
    ) -> list[tuple[float, float, float, float]]:
        """Iteratively merge any two boxes that overlap into their union bbox.

        Two boxes "overlap" when their intersection has positive area. Runs in
        O(N²) which is fine for the handful of zones per frame we deal with.
        """
        merged = list(boxes)
        changed = True
        while changed:
            changed = False
            for i in range(len(merged)):
                for j in range(i + 1, len(merged)):
                    ax1, ay1, ax2, ay2 = merged[i]
                    bx1, by1, bx2, by2 = merged[j]
                    if min(ax2, bx2) > max(ax1, bx1) and min(ay2, by2) > max(ay1, by1):
                        merged[i] = (
                            min(ax1, bx1), min(ay1, by1),
                            max(ax2, bx2), max(ay2, by2),
                        )
                        merged.pop(j)
                        changed = True
                        break
                if changed:
                    break
        return merged

    def _pad_phone_zone(
        self, x1: float, y1: float, bw: float, bh: float, w: int, h: int,
    ) -> tuple[float, float, float, float]:
        """Pad a dashboard bounding box and return as normalized coordinates.

        Padding applies to the left, right, and bottom sides only — NOT the
        top. The dashboard / mounted-phone area is at the bottom of the frame;
        extending the zone upward risks catching a rider further ahead on the
        same trail, causing their plate to be wrongly filtered.
        """
        px, py = bw * self._PHONE_PAD, bh * self._PHONE_PAD
        nx = max(0.0, (x1 - px)) / w
        ny = max(0.0, y1) / h  # no top padding
        nw = min(float(w), bw + 2 * px) / w
        # Height = original + bottom padding only, clamped to frame bottom.
        nh = min(float(h) - max(0.0, y1), bh + py) / h
        return (nx, ny, nw, nh)

    @staticmethod
    def _nms_xyxy(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
        """Plain NMS on an (N, 4) xyxy array. Returns indices to keep."""
        if len(boxes) == 0:
            return []
        order = np.argsort(-scores)
        keep: list[int] = []
        while len(order) > 0:
            i = int(order[0])
            keep.append(i)
            if len(order) == 1:
                break
            xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
            yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
            xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
            yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
            inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
            area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
            area_rest = (
                (boxes[order[1:], 2] - boxes[order[1:], 0])
                * (boxes[order[1:], 3] - boxes[order[1:], 1])
            )
            iou = inter / np.maximum(area_i + area_rest - inter, 1e-9)
            order = order[1:][iou < iou_threshold]
        return keep

    def update_phone_zones(self, frame: np.ndarray) -> None:
        """Re-detect phone zones if enough frames have elapsed.

        Strategy: keep trying every frame until a phone is found, then
        re-check every _PHONE_REDETECT_EVERY frames to track movement.
        """
        if not self._exclude_phones:
            return
        self._phone_frame_counter += 1
        # If we haven't found a phone yet, try every frame
        if not self._phone_zones:
            zones = self.detect_phones(frame)
            if zones:
                self._phone_zones = zones
            return
        # Once found, periodically refresh (clear if phone disappears)
        if self._phone_frame_counter % self._phone_redetect_every == 0:
            self._phone_zones = self.detect_phones(frame)

    @property
    def current_phone_zones(self) -> list[tuple[float, float, float, float]]:
        """Return a copy of the phone exclusion zones active on the last
        processed frame. Empty list when ``exclude_phones`` is disabled or no
        phone has been detected yet. For single-frame callers
        (``detect_frame`` / ``detect_frame_tiled``) this lets the UI overlay
        the zone that the filter just used without reaching into private state.
        """
        return list(self._phone_zones)

    def _filter_phone_zones(self, boxes: list[PlateBox]) -> list[PlateBox]:
        """Remove plate detections whose center falls inside a phone exclusion zone."""
        if not self._phone_zones:
            return boxes
        filtered = []
        for box in boxes:
            cx = box.x + box.w / 2
            cy = box.y + box.h / 2
            inside = False
            for zx, zy, zw, zh in self._phone_zones:
                if zx <= cx <= zx + zw and zy <= cy <= zy + zh:
                    inside = True
                    break
            if not inside:
                filtered.append(box)
        return filtered

    # --- Ultralytics backend ---

    def _detect_ultralytics(self, frame: np.ndarray) -> list[PlateBox]:
        """Run detection using ultralytics YOLO (handles preprocessing internally)."""
        h, w = frame.shape[:2]
        results = self._model.predict(
            frame, conf=self._threshold, imgsz=self.INPUT_SIZE,
            device=self._device, verbose=False,
        )
        boxes = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0].cpu())
                boxes.append(PlateBox(
                    x=x1 / w, y=y1 / h,
                    w=(x2 - x1) / w, h=(y2 - y1) / h,
                    confidence=conf,
                ))
        return boxes

    # --- onnxruntime backend ---

    def _infer_ort(self, image: np.ndarray) -> np.ndarray:
        """Run inference with onnxruntime on a 640x640 image."""
        blob = image.astype(np.float32) / 255.0
        blob = blob[:, :, ::-1]  # BGR -> RGB
        blob = blob.transpose(2, 0, 1)  # HWC -> CHW
        blob = blob[np.newaxis]
        blob = np.ascontiguousarray(blob)
        return self._session.run(None, {self._input_name: blob})[0]

    # --- cv2.dnn backend ---

    def _infer_cv2(self, image: np.ndarray) -> np.ndarray:
        """Run inference with cv2.dnn on a 640x640 image."""
        blob = cv2.dnn.blobFromImage(
            image, 1.0 / 255.0, swapRB=True, crop=False,
        )
        self._net.setInput(blob)
        return self._net.forward()

    # --- Shared utilities ---

    def _letterbox(self, frame: np.ndarray) -> tuple[np.ndarray, float, tuple[int, int]]:
        """Resize with letterboxing (preserve aspect ratio, pad with gray)."""
        h, w = frame.shape[:2]
        scale = min(self.INPUT_SIZE / w, self.INPUT_SIZE / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (new_w, new_h))

        canvas = np.full(
            (self.INPUT_SIZE, self.INPUT_SIZE, 3), 114, dtype=np.uint8,
        )
        pad_w = (self.INPUT_SIZE - new_w) // 2
        pad_h = (self.INPUT_SIZE - new_h) // 2
        canvas[pad_h:pad_h + new_h, pad_w:pad_w + new_w] = resized
        return canvas, scale, (pad_w, pad_h)

    def detect_clip(
        self,
        video_path: str | Path,
        start_time: float,
        end_time: float,
        clip_index: int = 0,
        progress_callback: Callable[[int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        tiled: bool = True,
        temporal_filter: bool = True,
        min_track_length: int = 3,
    ) -> ClipPlateData:
        """Detect plates in a clip time range. Returns ClipPlateData.

        Uses OpenCV ``CAP_PROP_POS_FRAMES`` seeking — the same decoder
        that ``grab_frame()`` (blur preview) and the blur processor use.
        This guarantees detection coordinates match the preview and
        export exactly, avoiding the spatial mismatch between FFmpeg
        pipe and OpenCV decoders for HEVC video.
        """
        return self._detect_clip_opencv(
            video_path, start_time, end_time, clip_index,
            progress_callback, cancelled, tiled,
            temporal_filter, min_track_length,
        )

    def _detect_clip_opencv(
        self,
        video_path: str | Path,
        start_time: float,
        end_time: float,
        clip_index: int = 0,
        progress_callback: Callable[[int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        tiled: bool = True,
        temporal_filter: bool = True,
        min_track_length: int = 3,
    ) -> ClipPlateData:
        """OpenCV fallback for detect_clip (used when FFmpeg is not available)."""
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps)
        total_frames = max(1, end_frame - start_frame)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        self._phone_zones = []
        self._phone_frame_counter = 0
        result = ClipPlateData(clip_index=clip_index)
        frames_done = 0
        max_conf_seen = 0.0

        for frame_num in range(start_frame, end_frame):
            if cancelled and cancelled():
                break
            ret, frame = cap.read()
            if not ret:
                break
            if self._verbose:
                self._current_frame_num = frame_num
                self._frame_header_printed = False
            detect_fn = self.detect_frame_tiled if tiled else self.detect_frame
            boxes = detect_fn(frame)
            if boxes:
                result.detections[frame_num] = boxes
                best = max(b.confidence for b in boxes)
                if best > max_conf_seen:
                    max_conf_seen = best
            if self._exclude_phones and self._phone_zones:
                result.phone_zones[frame_num] = list(self._phone_zones)
            frames_done += 1
            if progress_callback:
                progress_callback(frames_done, total_frames)

        cap.release()
        if progress_callback:
            progress_callback(frames_done, total_frames)
        if self._verbose:
            print(f"[PlateDetect] Clip {clip_index} (OpenCV fallback): "
                  f"processed {frames_done} frames, max_conf={max_conf_seen:.4f}")
        if temporal_filter:
            from trailvideocut.plate.temporal_filter import filter_temporal_continuity
            result = filter_temporal_continuity(result, min_track_length=min_track_length)
        return result

    def _parse_output(
        self, outputs: np.ndarray, img_w: int, img_h: int,
        ratio: float = 1.0, pad_w: int = 0, pad_h: int = 0,
    ) -> list[PlateBox]:
        """Parse YOLO output into normalized PlateBox list."""
        preds = outputs[0]

        if preds.size == 0:
            return []

        if preds.ndim == 2 and preds.shape[0] < preds.shape[1]:
            preds = preds.T

        boxes = []
        for det in preds:
            cx, cy, bw, bh = det[0], det[1], det[2], det[3]
            conf = float(np.max(det[4:]))

            if conf < self._threshold:
                continue

            x1_px = (cx - bw / 2 - pad_w) / ratio
            y1_px = (cy - bh / 2 - pad_h) / ratio
            w_px = bw / ratio
            h_px = bh / ratio

            x1 = x1_px / img_w
            y1 = y1_px / img_h
            w = w_px / img_w
            h = h_px / img_h

            x1 = max(0.0, min(1.0, x1))
            y1 = max(0.0, min(1.0, y1))
            w = min(w, 1.0 - x1)
            h = min(h, 1.0 - y1)

            if w > 0.005 and h > 0.005:
                boxes.append(PlateBox(x=x1, y=y1, w=w, h=h, confidence=conf))

        if len(boxes) > 1:
            boxes = self._nms(boxes, iou_threshold=0.5)

        return boxes

    @staticmethod
    def _nms(boxes: list[PlateBox], iou_threshold: float) -> list[PlateBox]:
        """Non-maximum suppression using IoU OR center-distance proximity.

        Two boxes are considered duplicates if:
        - Their IoU exceeds *iou_threshold*, OR
        - The center of one box falls inside the other (common with tiled
          detections where the same plate produces different-sized boxes).
        """
        sorted_boxes = sorted(boxes, key=lambda b: b.confidence, reverse=True)
        keep: list[PlateBox] = []
        for box in sorted_boxes:
            if all(
                _iou(box, kept) < iou_threshold
                and not _center_inside(box, kept)
                and not _center_inside(kept, box)
                for kept in keep
            ):
                keep.append(box)
        return keep


def _iou(a: PlateBox, b: PlateBox) -> float:
    """Intersection over union of two boxes."""
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.w, b.x + b.w)
    y2 = min(a.y + a.h, b.y + b.h)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = a.w * a.h
    area_b = b.w * b.h
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center_inside(a: PlateBox, b: PlateBox) -> bool:
    """Return True if the center of *a* lies inside *b*."""
    cx = a.x + a.w / 2
    cy = a.y + a.h / 2
    return b.x <= cx <= b.x + b.w and b.y <= cy <= b.y + b.h
