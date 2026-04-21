## Purpose

Apply Gaussian blur to detected plate bounding-box regions during MP4 export so license plates are obscured in the final video. Blur is driven by the per-clip `ClipPlateData.detections` map and scales automatically with each plate's pixel dimensions.
## Requirements
### Requirement: Apply Gaussian blur to detected plate regions during export
The system SHALL apply Gaussian blur to all detected plate bounding box regions when rendering the final video via FFmpeg. Blur SHALL be applied frame-by-frame using the stored plate coordinates for each clip. Only MP4 export SHALL apply blur; OTIO export SHALL remain unchanged. Blur SHALL only be applied to frames within the detection range; frames before the first detection or after the last detection in a clip SHALL NOT be blurred. The per-clip frame window considered for blur SHALL be the clip's effective window — `[source_start_frame, source_end_frame + tail_frames(clip_index, plan, fps))` — as defined by the `plate-clip-transition-tail` capability. This matches the extended subclip range the assembler already extracts for non-last crossfade clips (`end = source_end + plan.crossfade_duration`), ensuring plates stored at tail frames are blurred in the exported MP4 rather than silently dropped at the core-range boundary.

#### Scenario: Export with detected plates
- **WHEN** the user exports a video with plate detection data available for clips 0 and 2
- **THEN** the exported video SHALL have all plate regions in clips 0 and 2 blurred, and clips without plate data SHALL render without blur

#### Scenario: Export with no plate data
- **WHEN** the user exports a video with no plate detection data
- **THEN** the export SHALL proceed identically to the current behavior with no blur applied

#### Scenario: Export with blur disabled
- **WHEN** the user exports a video with plate data available but `plate_blur_enabled` is set to `False`
- **THEN** the export SHALL proceed without applying any plate blur

#### Scenario: Plate detection starts mid-clip
- **WHEN** a clip spans frames 0-200 and plate detections exist only for frames 100-180
- **THEN** frames 0-99 SHALL NOT have any blur applied, frames 100-180 SHALL have blur applied to the plate regions, and frames 181-200 SHALL NOT have any blur applied

#### Scenario: Frame outside detection range returns no boxes
- **WHEN** `_get_boxes_for_frame()` is called with a frame number before the first detection key or after the last detection key
- **THEN** the method SHALL return an empty list, not the nearest detection's boxes

#### Scenario: Tail-region plate is blurred in the exported MP4
- **WHEN** a non-last crossfade clip's core range is frames 0–200 with a 6-frame tail, a plate is stored at source frame 203, and the user exports MP4 with blur enabled
- **THEN** source frame 203 SHALL be blurred in the exported output at the position stored in `detections[203]`, identical to how a core-range plate would be blurred

#### Scenario: Tail-region plate on a CUT plan is not reached
- **WHEN** the plan uses `CUT` transitions so `tail_frames == 0`
- **THEN** the blur path SHALL apply only to core-range frames as today — there is no tail to traverse

### Requirement: Automatic blur strength based on plate dimensions
Blur intensity SHALL be determined automatically from the plate's pixel dimensions. There is no per-plate or global blur strength setting. All detected plates are blurred; to exclude a plate the user deletes the detection. `TrailVideoCutConfig` SHALL include a `plate_blur_enabled` field (bool, default True) that acts as a master toggle.

#### Scenario: All detected plates are blurred
- **WHEN** a frame has 3 detected plates of different sizes
- **THEN** the system SHALL apply Gaussian blur to all 3 plates, with kernel sizes proportional to each plate's dimensions

#### Scenario: Global blur disabled skips all blur
- **WHEN** `plate_blur_enabled` is `False` and plate data exists
- **THEN** the export SHALL not apply any blur

### Requirement: Apply blur during MoviePy composition with calibrated frame mapping
The system SHALL apply blur per-frame using MoviePy's `transform()` function during video composition. Before applying blur to a clip, the system SHALL calibrate the frame offset by comparing MoviePy's first decoded frame against source frames (content-based MSE matching). Segments without plate data SHALL pass through unchanged.

#### Scenario: Mixed segments with and without plates
- **WHEN** a cut plan has 5 segments and only segments 1 and 3 have plate data
- **THEN** only segments 1 and 3 SHALL have blur applied; segments 0, 2, and 4 SHALL render without blur processing

#### Scenario: Drift-tolerant blur boxes
- **WHEN** blur is applied to a frame and the plate moves between adjacent frames
- **THEN** the blur region SHALL be expanded to the bounding-box union of plate positions at frames N-1, N, and N+1, ensuring the plate is covered even with ±1 frame timing drift

### Requirement: Progress reporting during blur pre-processing
The system SHALL report blur processing progress to the user via the existing progress callback mechanism. Progress SHALL reflect the combined effort of pre-processing and FFmpeg assembly.

#### Scenario: Progress during blur processing
- **WHEN** blur pre-processing is running for a segment with 300 frames
- **THEN** the progress callback SHALL be invoked periodically with the current frame count and total frame count

### Requirement: Blur kernel size scales with plate dimensions
The Gaussian blur kernel size SHALL scale automatically with the plate's pixel dimensions. The formula SHALL be: `kernel_size = max(3, min(plate_pixel_w, plate_pixel_h))`, ensuring the kernel is always odd. Larger plates get proportionally stronger blur so the content is fully obscured.

#### Scenario: Large plate gets large kernel
- **WHEN** a plate region is 200x100 pixels
- **THEN** the Gaussian kernel size SHALL be 99 (odd, scaled from min dimension 100)

#### Scenario: Small plate gets small kernel
- **WHEN** a plate region is 40x20 pixels
- **THEN** the Gaussian kernel size SHALL be 19 (odd, scaled from min dimension 20)

### Requirement: FFmpeg PlateBlurProcessor uses exact source-frame key lookup
When the export path invokes `PlateBlurProcessor.process_segment` (the primary FFmpeg route), for each source-video frame decoded at index `abs_frame` the blur box lookup MUST use key `abs_frame` against `ClipPlateData.detections` — the same integer key written by `PlateDetector.detect_plates` in `detector.py`. No additive, subtractive, or piecewise-keyframe-conditional offset SHALL be applied between `abs_frame` and the lookup key. This invariant applies to both exact-match lookup and the `_nearest_boxes` ±window fallback.

#### Scenario: Lookup key equals decoded frame index
- **WHEN** `PlateBlurProcessor.process_segment` decodes source frame N during a segment
- **THEN** the boxes used to blur that frame SHALL be retrieved via `detections[N]` (or the nearest detection within the configured window centred on N with the same keying), not `detections[N+1]` or `detections[N-1]`

#### Scenario: Mid-GOP seek does not introduce a lookup offset
- **WHEN** a segment's `cap.set(CAP_PROP_POS_FRAMES, seg_start_frame)` lands mid-GOP and OpenCV begins returning frames from `seg_start_frame` onward
- **THEN** the lookup key SHALL still equal the decoder's logical position counter (`seg_start_frame + frames_read_so_far`), with no piecewise pre-keyframe correction applied

#### Scenario: Exported pixels at source frame N match detections[N]
- **WHEN** a synthesized source clip has each source frame N encoded uniquely into a fixed pixel region (e.g. via a per-frame colour code) and a single plate detection at source frame K covers that region
- **THEN** decoding the output of `PlateBlurProcessor.process_segment` at the offset corresponding to source frame K SHALL show the region blurred, while the same region at source frames K-1 and K+1 SHALL still match the original per-frame encoding (unblurred)

### Requirement: Cross-surface source-frame alignment for MP4 export
Exported MP4 frames SHALL honour the cross-surface alignment invariant: for any source frame N, the pixels that end up in the exported MP4 at the timeline position corresponding to N reference the same `boxes[N]` that the preview overlay draws at source frame N. This requirement applies to the primary FFmpeg path; the MoviePy fallback's calibrated behaviour satisfies this invariant through its own calibration mechanism and is covered by the existing fallback requirement.

#### Scenario: Preview and MP4 export agree at the same source frame
- **WHEN** the preview overlay at source frame N shows a blur box positioned at box B and the user exports via the primary FFmpeg path
- **THEN** the exported MP4 at the timeline position corresponding to source frame N SHALL have blur applied at the same box B, modulo encoding rounding

### Requirement: Oriented-rectangle blur masks
When a plate box carries a non-zero rotation angle, the system SHALL apply the Gaussian blur through a mask whose blurred region is the rotated rectangle defined by `(centre_x, centre_y, width, height, angle)` rather than an axis-aligned bounding rectangle. The rotated-rectangle mask SHALL be produced by computing the four corner points via `cv2.boxPoints` and filling the convex polygon on a same-sized mask with `cv2.fillConvexPoly`, then applying the blur through that mask.

#### Scenario: Pixels outside the rotated polygon are unblurred
- **WHEN** a frame contains a single plate box with `angle = 20°` rendered by the MP4 export path
- **THEN** pixels inside the rotated quadrilateral defined by `(centre, width, height, 20°)` SHALL be blurred in the exported output, and pixels outside that quadrilateral but inside the box's axis-aligned envelope SHALL NOT be blurred (they SHALL match the source frame modulo encoding rounding)

#### Scenario: Axis-aligned boxes remain unaffected
- **WHEN** a frame contains only plate boxes with `angle == 0.0`
- **THEN** the blur output SHALL be pixel-identical to the pre-feature axis-aligned blur path (no behavioural regression)

### Requirement: Kernel sizing for oriented boxes uses the rotated rectangle's own dimensions
The Gaussian blur kernel size for a rotated-rectangle mask SHALL be computed from the rotated rectangle's own `width` and `height` (the plate-aligned extents), using the same formula as axis-aligned boxes: `kernel_size = max(3, min(plate_pixel_w, plate_pixel_h))`, rounded up to the nearest odd value. The kernel SHALL NOT be derived from the axis-aligned bounding envelope of the rotated rectangle.

#### Scenario: Rotated kernel matches plate-aligned dimensions
- **WHEN** a plate has rotated-rectangle dimensions 160×40 px at `angle = 25°` (its axis-aligned envelope would be larger)
- **THEN** the Gaussian kernel size SHALL be derived from `min(160, 40) == 40`, yielding an odd kernel size ≤ 40 — the same result as if the plate were axis-aligned at 160×40

### Requirement: Drift-tolerant union for oriented boxes
The existing drift-tolerant blur behaviour (unioning boxes at frames N-1, N, and N+1) SHALL extend to oriented boxes by unioning the rotated polygons on the same mask. The union SHALL be computed by filling each neighbour's rotated polygon onto the single mask before applying the blur. The union SHALL NOT fall back to each box's axis-aligned envelope when any participant is oriented.

#### Scenario: Oriented neighbours are polygon-unioned
- **WHEN** frame N has a plate at `angle = 10°` and frame N-1 has the same plate at a slightly different centre with `angle = 10°`
- **THEN** the mask applied at frame N SHALL be the union of the two rotated polygons, and pixels outside the union SHALL NOT be blurred

