## ADDED Requirements

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
