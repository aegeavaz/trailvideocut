## Context

The plate detection feature uses `PlateDetector` (onnxruntime + YOLOv8 ONNX) and `model_manager` for model caching. The CLI uses Typer with commands `cut`, `analyze`, and `ui`. Plates in motorcycle POV footage are typically 20-40px wide in 1920x1080 frames. After letterboxing to 640x640, they become ~7-13px — below YOLO's effective detection threshold (~32px). The model works fine on larger plates; the problem is input resolution.

## Goals / Non-Goals

**Goals:**
- Add tiled detection: split frame into overlapping 320x320 crops, upscale to 640x640, detect, map back
- Support GPU acceleration via `onnxruntime-gpu` with batch inference across tiles
- Default to tiled detection in both CLI and UI since target plates are small
- CLI `detect-plates` command with `--tiled/--no-tiled` flag and `--model` option
- Save annotated frame PNGs + `detections.csv` for debugging

**Non-Goals:**
- OCR / plate text reading
- Training a custom model
- Video output (only static frame PNGs)

## Decisions

### 1. Tiling strategy: 320x320 crop → 640x640 upscale

A 320x320 crop upscaled to 640x640 gives 2x magnification: a 20px plate becomes 40px, a 40px plate becomes 80px — well within YOLO's detection range. With 50% overlap (stride=160px), tiles cover the full frame and plates at tile boundaries appear in multiple tiles. NMS merges duplicates.

Tile count for 1920x1080: ~11 x 6 = ~66 tiles per frame. With GPU batch inference (batch size 8), this is ~8 passes × ~5ms = ~40ms per frame.

### 2. GPU batch inference via onnxruntime

Stack multiple tile blobs into a single batch tensor and run one inference call. This maximizes GPU utilization. Fall back to sequential when CPU-only.

### 3. Single `plate` dependency: `onnxruntime-gpu`

Replace `onnxruntime` with `onnxruntime-gpu` in `pyproject.toml`'s `plate` extra. It includes CUDA support and falls back to CPU automatically. No separate optional needed.

### 4. Keep YOLOv8n model

The nano model is fast and accurate enough when plates are magnified via tiling. No need for a larger model — the performance/accuracy trade-off favors nano + tiling over medium + single-pass.

### 5. Draw boxes with OpenCV, not Qt

Use `cv2.rectangle` and `cv2.putText` for CLI debug output. No PySide6 dependency.

### 6. CSV log format

One row per detection: frame_number, timestamp_s, x, y, w, h, x_px, y_px, w_px, h_px, confidence, tile_x, tile_y.

## Risks / Trade-offs

- **Processing time**: ~66 tiles per frame is ~40ms GPU, ~1.3s CPU. Mitigated by `--every-n` sampling and time range filtering.
- **Disk space**: Saving PNGs for many frames. Mitigated by `--start`/`--end` and `--every-n`.
- **Tile boundary duplicates**: NMS handles this, but threshold tuning may be needed.
