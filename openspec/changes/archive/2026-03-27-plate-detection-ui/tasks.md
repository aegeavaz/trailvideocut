## 1. Data Model & Dependencies

- [x] 1.1 Add `ultralytics` or ONNX model dependency to `pyproject.toml` (optional extra like `[plate]`)
- [x] 1.2 Create `src/trailvideocut/plate/__init__.py` and `src/trailvideocut/plate/models.py` with `PlateBox` and `ClipPlateData` dataclasses
- [x] 1.3 Implement model download/cache utility in `src/trailvideocut/plate/model_manager.py` (download ONNX model on first use, cache in platform data dir)

## 2. Detection Engine

- [x] 2.1 Create `src/trailvideocut/plate/detector.py` with `PlateDetector` class that loads ONNX model via OpenCV DNN
- [x] 2.2 Implement frame extraction and detection loop with configurable confidence threshold
- [x] 2.3 Add progress callback support (called every N frames with current/total fraction)
- [x] 2.4 Add cancellation flag check between frames, returning partial results on cancel
- [x] 2.5 Write unit tests for `PlateDetector` (mock model, verify output format, threshold filtering, cancellation)

## 3. Background Worker

- [x] 3.1 Create `PlateDetectionWorker(QThread)` in `src/trailvideocut/ui/workers.py` following `AnalysisWorker` pattern
- [x] 3.2 Emit signals: `progress(int clip_index, int frame, int total_frames)`, `finished(dict results)`, `error(str message)`
- [x] 3.3 Support cancellation via `stop()` method (sets flag checked by detector)
- [x] 3.4 Handle single-clip vs all-clips detection scope

## 4. Plate Overlay Widget

- [x] 4.1 Create `src/trailvideocut/ui/plate_overlay.py` with `PlateOverlayWidget(QWidget)` that renders over `QVideoWidget`
- [x] 4.2 Implement coordinate mapping: normalized plate coords -> widget pixel coords accounting for letterboxing/aspect ratio
- [x] 4.3 Implement `paintEvent` to draw bounding boxes (semi-transparent fill, colored border) for current frame's detections
- [x] 4.4 Implement box selection on mouse click (hit test, smallest-area-wins for overlaps, visual highlight + resize handles)
- [x] 4.5 Implement drag-to-move for selected box (clamp to video bounds, update normalized coords on release)
- [x] 4.6 Implement resize handles on selected box (corner + edge handles, minimum size enforcement, update normalized coords)
- [x] 4.7 Implement Delete/Backspace key handler to remove selected box from detection data
- [x] 4.8 Implement "Add plate box" action: clone position from nearest prior detection or use default centered box, mark as `manual: true`, auto-select new box

## 5. Review Page Integration

- [x] 5.1 Add "Detect Plates" button to Review page toolbar (enabled only when clips are available)
- [x] 5.2 Wire button click to create and start `PlateDetectionWorker` with correct clip scope (selected clip or all)
- [x] 5.3 Add progress bar + Cancel button for detection in progress
- [x] 5.4 Store detection results (`dict[int, ClipPlateData]`) on Review page, keyed by clip index
- [x] 5.5 Instantiate and position `PlateOverlayWidget` over the video player widget
- [x] 5.6 Connect video player position changes to overlay update (lookup current frame, repaint boxes)
- [x] 5.7 Add "Show Plates" toggle checkbox to show/hide the overlay
- [x] 5.8 Add "Add Plate" button (enabled when overlay is visible and video is paused on a frame)
- [x] 5.9 Handle re-detection: replace auto-detected boxes while preserving manual boxes

## 6. Testing & Polish

- [x] 6.1 Test overlay coordinate mapping at various window sizes and video aspect ratios
- [x] 6.2 Test box interaction: select, move, resize, delete, add manual
- [x] 6.3 Test detection workflow: single clip, all clips, cancel, re-run
- [x] 6.4 Verify overlay hides/shows correctly with the toggle
- [x] 6.5 Verify no regressions in existing Review page functionality (timeline, preview mode, clip editing)
