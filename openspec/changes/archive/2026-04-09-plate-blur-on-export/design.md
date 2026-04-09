## Context

TrailVideoCut exports final videos via FFmpeg filter graphs built in `assembler.py`. The pipeline constructs per-segment inputs with `-ss`/`-t` seeking and chains them with xfade or concat filters. Plate detection results (stored as normalized bounding boxes in `ClipPlateData`) are currently only visualized in the `PlateOverlayWidget` but are completely ignored during export.

Plate bounding box positions vary frame-to-frame (plates move as the camera pans), so a static FFmpeg filter expression cannot encode position changes. A dynamic per-frame approach is required.

## Goals / Non-Goals

**Goals:**
- Apply Gaussian blur to detected plate regions during video export
- Support per-plate configurable blur strength (stored in `PlateBox.blur_strength`)
- Support a global default blur strength in config
- Provide a blur preview on the review page so users can see the blur effect before exporting
- Maintain export quality (no unnecessary re-encoding)
- Keep the blur pipeline testable and decoupled from the assembly pipeline

**Non-Goals:**
- Blur in OTIO/DaVinci Resolve export (OTIO references source files, blur must be applied in the NLE)
- Pixelation or mosaic effects (only Gaussian blur for now)
- Automatic blur without prior detection (user must run detection first)

## Decisions

### Decision 1: Apply blur via MoviePy transform() with calibrated frame mapping

**Choice**: Apply blur per-frame inside MoviePy's `transform()` function during composition. A content-based calibration step determines the exact frame offset between MoviePy's FFmpeg decoder and OpenCV's frame indexing. Blur boxes are expanded to cover ±1 frame of plate movement (drift tolerance).

**Alternatives considered and rejected**:
- **Pre-process segments with OpenCV → temp files → FFmpeg xfade**: Cleanly separates blur from assembly, but FFmpeg's `fps=` filter **always resamples** frames even with matching timebases. This caused ±1 frame drift identical to the MoviePy issue. Attempts to avoid `fps=` (using `settb`/`setpts`) failed because xfade requires frame rate metadata that only `fps=` provides. MKV timebase quantization (1/1000) added further drift.
- **Pre-blurred frames → ImageSequenceClip**: MoviePy's internal `find_image_index()` uses a floor-based lookup susceptible to floating-point drift, causing the same frame misalignment.
- **In-memory numpy arrays → ImageSequenceClip**: Same `find_image_index` issue.
- **Post-process output video**: Re-encoding through FFmpeg filter_complex degraded quality (42MB vs 400MB output).
- **FFmpeg-native filter graph (crop+boxblur+overlay)**: Per-frame position expressions are impractical.

**Rationale**: The `transform()` approach applies blur to the actual frame MoviePy decodes — no temp files, no re-encoding, no container timing issues. The calibration + drift-tolerant expansion handles the unavoidable ±1 frame timing imprecision present in all video processing pipelines.

### Decision 2: PlateBlurProcessor class with segment-level processing

**Choice**: Create a new `PlateBlurProcessor` class in `trailvideocut/plate/blur.py` responsible for:
1. Accepting a video path, segment time range, clip plate data, and FPS
2. Reading frames with OpenCV (`cv2.VideoCapture`)
3. Applying `cv2.GaussianBlur` to each plate's pixel region per frame
4. Writing blurred frames to a temporary file with `cv2.VideoWriter`
5. Returning the path to the temporary file

**Rationale**: Encapsulates all blur logic. The assembler only needs to know "use this file instead of seeking into the source." Easily testable with synthetic frames and known plate positions.

### Decision 3: blur_strength as a float field on PlateBox (0.0–1.0)

**Choice**: Add `blur_strength: float = 1.0` to `PlateBox`. The value maps to the Gaussian kernel size: `kernel_size = int(blur_strength * max_kernel)` where `max_kernel` scales with plate pixel dimensions. A value of `0.0` means no blur; `1.0` means maximum blur (plate completely unreadable).

**Rationale**: Normalized 0–1 range is intuitive for UI sliders and decoupled from pixel resolution. The actual kernel size adapts to plate dimensions so small and large plates get proportionally equivalent blur.

### Decision 4: Global default blur strength in TrailVideoCutConfig

**Choice**: Add `plate_blur_strength: float = 1.0` and `plate_blur_enabled: bool = True` to `TrailVideoCutConfig`. New plates inherit the global default. The `plate_blur_enabled` flag provides a quick toggle on the export page.

**Rationale**: Users want a global control without adjusting each plate individually. The enabled flag lets users skip blur entirely without clearing plate data.

### Decision 5: Integration point in VideoAssembler

**Choice**: Add a `plate_data` parameter to `VideoAssembler.assemble()` (optional, defaults to `None`). Before building the FFmpeg command, the assembler calls `PlateBlurProcessor` for each segment that has plate data, producing temporary blurred files. The segment input paths in the FFmpeg command switch from the source video to the temp files. Temp files are cleaned up after assembly completes.

**Rationale**: Minimal change to existing assembly logic. The filter graph construction (`_build_filter_complex`, `_build_filter_complex_hardcut`) remains unchanged — only the input file paths change.

### Decision 6: Frame number mapping with calibration and drift tolerance

**Choice**: Plate data stores **absolute** frame numbers (from video start). Frame mapping uses three layers:

1. **Calibration**: Before applying blur, compare MoviePy's first decoded frame (`sub.get_frame(0)`) against source frames at `expected_frame ± 3` using pixel MSE. This determines a constant offset between MoviePy's decoder and OpenCV's `CAP_PROP_POS_FRAMES` indexing.
2. **Round-based lookup**: Use `round((source_start + t) * fps)` instead of `int()` to avoid floating-point truncation that causes ~40% of frames to map to the wrong index.
3. **Drift-tolerant expansion**: For each frame, expand the blur box to the bounding-box union of plate positions at frames N-1, N, and N+1 (`expand_boxes_for_drift()`). This handles the ±1 frame timing drift that persists after calibration — caused by MoviePy's FFmpeg decoder resolving different frames than predicted for specific scattered timestamps.

**Rationale**: No time-based frame computation can perfectly predict which source frame MoviePy's FFmpeg decoder will return at every timestamp. The three-layer approach fixes the constant offset (calibration), reduces per-frame errors (`round`), and makes the remaining drift invisible (expanded boxes). The expansion adapts to plate velocity — negligible for slow movement, larger for fast movement.

### Decision 7: Blur preview via snapshot-and-overlay on PlateOverlayWidget

**Choice**: When blur preview is enabled, grab the current video frame using OpenCV (`cv2.VideoCapture` seeking to the current position), extract plate regions as numpy arrays, apply `cv2.GaussianBlur`, convert each blurred region to a `QPixmap`, and paint them on the `PlateOverlayWidget` in `paintEvent()` at the correct positions. The preview updates on frame change (seek, step, or playback position change).

**Alternatives considered**:
- **QVideoSink frame interception**: Replace `QGraphicsVideoItem` output with a custom `QVideoSink` that intercepts every frame, applies blur, and re-renders. This would provide smooth real-time blur during playback but requires significant restructuring of the video pipeline and adds per-frame overhead even when blur is off.
- **QGraphicsBlurEffect on scene items**: Qt's `QGraphicsBlurEffect` applies to entire `QGraphicsItem`s, not sub-regions. Would require splitting the video into sub-items per plate region, which is impractical.
- **Render blurred full frame as overlay**: Grab the entire frame, blur plate regions, and paint the whole frame as an overlay. Wasteful — only the plate regions need to be overlaid.

**Rationale**: The snapshot-and-overlay approach reuses the existing `PlateOverlayWidget` painting infrastructure with minimal changes. It only processes plate regions (small crops), so performance is excellent. The same `cv2.GaussianBlur` function used for export is used for preview, guaranteeing visual consistency. Frame grabbing via OpenCV is a one-shot operation per frame change — not continuous — so it doesn't impact playback smoothness. The approach is well-suited to the review workflow where users step through frames or pause to inspect plates.

**Implementation detail**: A helper function `grab_frame(video_path, time_seconds)` in `plate/blur.py` opens the video, seeks to the timestamp, reads one frame, and closes the capture. The `PlateOverlayWidget` stores a list of `QPixmap` tiles (one per plate) and paints them in `paintEvent()` before drawing the bounding box outlines. When blur preview is off, the pixmaps are cleared and the widget reverts to the current box-only rendering.

## Risks / Trade-offs

- **Temp file disk space**: Each segment produces a temporary video file. For long videos with many segments, this could consume significant disk space. → **Mitigation**: Process and clean up segments one at a time if memory is a concern; use the same codec/quality settings to avoid bloat. Temp files are deleted in a `finally` block.

- **Quality loss from re-encoding segments**: Pre-processing requires decode + re-encode of segments that have plates. → **Mitigation**: Use lossless or near-lossless encoding for temp files (e.g., `ffv1` or high-CRF `libx264`). The final assembly re-encodes anyway, so one intermediate step at near-lossless quality has negligible impact.

- **Performance overhead**: OpenCV frame-by-frame processing is slower than native FFmpeg filtering. → **Mitigation**: Only segments with plate data are pre-processed. Segments without plates pass through unchanged. Use batch processing where possible. Progress callback keeps the user informed.

- **Crossfade overlap frames**: In crossfade mode, segments are extended by `crossfade_duration` to create overlap. Plate data may not cover these extra frames. → **Mitigation**: For frames beyond the plate data range, extrapolate from the nearest detection frame. The extension is typically very short (0.2s).

- **±1 frame timing drift**: All video processing pipelines (MoviePy, FFmpeg) introduce scattered ±1 frame timing errors due to floating-point time→frame conversion and decoder-specific seek behavior. → **Mitigation**: Content-based calibration fixes the constant offset; velocity-based blur box expansion (`expand_boxes_for_drift`) makes the blur robust to the remaining per-frame drift. The blur region is slightly larger than the plate (proportional to plate movement speed) but always covers it.

- **Blur preview latency on seek**: Each frame change triggers an OpenCV `VideoCapture` open+seek+read, which may introduce a small delay (~20-50ms for local files). → **Mitigation**: Run the frame grab in a background thread and update the overlay asynchronously. If the user seeks again before the grab completes, cancel the pending grab. During continuous playback, throttle preview updates to avoid stacking frame grabs.
