## 1. CLI Command (done)

- [x] 1.1 Add `detect_plates` command to `src/trailvideocut/cli.py` with Typer options
- [x] 1.2 Implement model auto-download with Rich progress
- [x] 1.3 Implement frame iteration loop with `--every-n` sampling
- [x] 1.4 Draw detection boxes on each frame with OpenCV, save as PNG
- [x] 1.5 Write `detections.csv` with header + one row per detection
- [x] 1.6 Add Rich progress bar with ETA

## 2. Tiled Detection

- [x] 2.1 Add `detect_frame_tiled(frame)` method to `PlateDetector` in `detector.py`: generate overlapping 320x320 tiles, upscale to 640x640, detect, map coordinates back to original frame
- [x] 2.2 Add coordinate mapping: tile-space normalized coords → original frame normalized coords accounting for tile offset and upscale factor
- [x] 2.3 Add cross-tile NMS to merge duplicate detections from overlapping tiles
- [x] 2.4 Add `_infer_ort_batch(tiles)` method for GPU batch inference: stack tiles into single batch tensor
- [x] 2.5 Add `tiled` parameter to `detect_clip()` to choose between tiled and single-pass detection

## 3. CLI + UI Integration

- [x] 3.1 Add `--tiled/--no-tiled` flag to CLI `detect-plates` command (default: tiled)
- [x] 3.2 Wire CLI to call `detect_frame_tiled()` when tiled mode is on
- [x] 3.3 Update `PlateDetectionWorker` in `workers.py` to pass `tiled=True`
- [x] 3.4 Update `review_page.py` to enable tiled detection by default (worker defaults to tiled=True)

## 4. Dependencies

- [x] 4.1 Change `plate` extra in `pyproject.toml` from `onnxruntime` to `onnxruntime-gpu`

## 5. Testing

- [x] 5.1 Test tiled detection on synthetic image with small plate (30px wide) — verify detection
- [x] 5.2 Test coordinate mapping: box position in tiled mode matches actual plate position
- [x] 5.3 Test NMS: overlapping tiles produce single merged detection
- [x] 5.4 Test CLI with `--tiled` and `--no-tiled` flags
- [x] 5.5 Run full test suite — no regressions
