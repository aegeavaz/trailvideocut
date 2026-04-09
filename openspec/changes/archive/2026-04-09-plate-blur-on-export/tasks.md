## 1. Data Model & Persistence

- [x] 1.1 Add `blur_strength: float = 1.0` field to `PlateBox` dataclass in `plate/models.py`
- [x] 1.2 Update `save_plates()` in `plate/storage.py` to serialize `blur_strength` in the sidecar JSON
- [x] 1.3 Update `load_plates()` in `plate/storage.py` to deserialize `blur_strength` with fallback default of `1.0` for legacy files
- [x] 1.4 Write unit tests for round-trip serialization of `blur_strength` and backward compatibility with legacy sidecar files

## 2. Configuration

- [x] 2.1 Add `plate_blur_strength: float = 1.0` and `plate_blur_enabled: bool = True` fields to `TrailVideoCutConfig` in `config.py`
- [x] 2.2 Wire global default `plate_blur_strength` into plate detection so newly detected plates inherit the configured default value

## 3. Core Blur Processor

- [x] 3.1 Create `plate/blur.py` with `PlateBlurProcessor` class: constructor accepts video path, segment start/duration, clip plate data, FPS, and frame dimensions
- [x] 3.2 Implement `process_segment()` method: read frames with `cv2.VideoCapture`, apply `cv2.GaussianBlur` to each plate region per frame, write to temp file with `cv2.VideoWriter`
- [x] 3.3 Implement blur kernel scaling: `kernel_size = max(3, int(blur_strength * min(plate_px_w, plate_px_h)))`, ensure kernel is always odd
- [x] 3.4 Implement `apply_blur_to_frame(frame, boxes)` as a standalone function that applies blur to plate regions on a single numpy frame — shared by both export and preview
- [x] 3.5 Implement `grab_frame(video_path, time_seconds)` helper: opens video with `cv2.VideoCapture`, seeks to timestamp, reads one frame, returns numpy array (or None on failure)
- [x] 3.6 Add progress callback support to `process_segment()` for per-frame progress reporting
- [x] 3.7 Handle edge cases: plates with `blur_strength=0.0` skipped, frames without plate data pass through unmodified, plates partially outside frame bounds are clamped
- [x] 3.8 Write unit tests for `PlateBlurProcessor` and `apply_blur_to_frame` using synthetic frames with known plate positions and verifiable blur application

## 4. Assembler Integration

- [x] 4.1 Add optional `plate_data: dict[int, ClipPlateData] | None` parameter to `VideoAssembler.assemble()` method
- [x] 4.2 Implement pre-processing step in `assemble()`: before building FFmpeg command, call `PlateBlurProcessor` for each segment that has plate data, collect temp file paths
- [x] 4.3 Modify FFmpeg input construction in `_assemble_ffmpeg_xfade()` and `_assemble_ffmpeg_hardcut()` to use temp file paths for pre-processed segments instead of seeking into the source video
- [x] 4.4 Add cleanup logic in `finally` block to delete all temporary pre-processed segment files after assembly
- [x] 4.5 Skip blur pre-processing entirely when `config.plate_blur_enabled` is `False`
- [x] 4.6 Write integration tests verifying that segments with plate data use temp files and segments without plate data use original source

## 5. UI - Per-Plate Blur Slider

- [x] 5.1 Add a blur strength `QSlider` (0–100, mapped to 0.0–1.0) to the plate controls section on the review page, visible only when a plate is selected
- [x] 5.2 Connect slider value changes to update the selected `PlateBox.blur_strength` and trigger sidecar save
- [x] 5.3 Update slider value when plate selection changes (reflect each plate's current `blur_strength`)
- [x] 5.4 Add blur strength percentage label next to the slider for readability

## 6. UI - Overlay Visual Feedback

- [x] 6.1 In `PlateOverlayWidget.paintEvent()`, draw a small percentage label (e.g., "50%") on plates with non-default `blur_strength` (not 1.0)
- [x] 6.2 Style the label to be readable (small font, semi-transparent background, positioned at top-right of the plate box)

## 7. UI - Blur Preview on Review Page

- [x] 7.1 Add a "Preview Blur" toggle button to the plate controls section on the review page
- [x] 7.2 Implement `BlurPreviewWorker` (or use a lightweight QRunnable): on frame change, call `grab_frame()` to read the current frame, then call `apply_blur_to_frame()` for all plates, crop blurred regions, convert each to `QPixmap`
- [x] 7.3 Extend `PlateOverlayWidget` to store a list of `(QRectF, QPixmap)` blur tiles and paint them in `paintEvent()` before the bounding box outlines
- [x] 7.4 Connect the preview toggle and frame position changes to trigger blur tile updates; clear tiles when preview is disabled or frame has no plates
- [x] 7.5 Add throttling: during continuous playback, limit blur preview updates to at most once every 100ms; cancel pending grabs when a new seek occurs
- [x] 7.6 Disable the "Preview Blur" button when no plate data exists for the current clip

## 8. UI - Export Page Toggle

- [x] 8.1 Add a "Blur detected plates" checkbox on the export page bound to `config.plate_blur_enabled`
- [x] 8.2 Add a global default blur strength slider on the export page bound to `config.plate_blur_strength`
- [x] 8.3 Pass loaded plate data from the review page through to the assembler when export is triggered

## 9. End-to-End Validation

- [ ] 9.1 Manual test: detect plates on a test video, adjust blur strength per plate, export, and verify blur appears correctly at expected positions (manual)
- [ ] 9.2 Manual test: export with blur disabled and verify no blur is applied (manual)
- [ ] 9.3 Manual test: load a legacy sidecar file (without `blur_strength`) and verify plates default to full blur (manual)
- [ ] 9.4 Manual test: enable blur preview on review page, step through frames, and verify blurred regions match expected blur strength and position (manual)
- [ ] 9.5 Manual test: toggle blur preview on/off and verify overlay switches cleanly between blurred patches and box-only display (manual)
