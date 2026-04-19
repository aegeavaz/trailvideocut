## Purpose

The plate detector runs an ONNX license-plate detection model against video clips and returns normalized bounding boxes per frame. It supports single-pass and tiled detection, a configurable confidence threshold, cached model loading, progress reporting, cancellation, and — when enabled — a dashboard-phone exclusion filter whose active zones are recorded per frame for UI debugging. All detection output is expressed as normalized `PlateBox` objects so downstream consumers (preview, blur, export) can reason in resolution-independent coordinates.
## Requirements
### Requirement: Detect plates in video frames
The system SHALL process video frames from a given time range and return bounding box coordinates for all detected license plates. Detection SHALL use an ONNX-based model loaded via OpenCV DNN. Results SHALL be returned as normalized coordinates (0-1 range) relative to the frame dimensions.

#### Scenario: Successful detection on a clip
- **WHEN** the detector is given a video file path, start time, and end time
- **THEN** it SHALL extract frames at the video's native FPS, run detection on each frame, and return a dictionary mapping frame numbers to lists of `PlateBox` objects

#### Scenario: No plates found in a frame
- **WHEN** a frame contains no detectable license plates
- **THEN** the frame SHALL be omitted from the results dictionary (no empty list entry)

#### Scenario: Multiple plates in a single frame
- **WHEN** a frame contains multiple license plates
- **THEN** all detected plates SHALL be returned as separate `PlateBox` entries for that frame

### Requirement: Configurable confidence threshold
The system SHALL accept a confidence threshold parameter (default 0.5). Only detections with confidence >= threshold SHALL be included in results.

#### Scenario: Low-confidence detection filtered out
- **WHEN** a plate is detected with confidence 0.3 and the threshold is 0.5
- **THEN** that detection SHALL NOT appear in the results

#### Scenario: High-confidence detection included
- **WHEN** a plate is detected with confidence 0.8 and the threshold is 0.5
- **THEN** that detection SHALL appear in the results with its confidence value preserved

### Requirement: Model loading and caching
The system SHALL load the ONNX model from a local cache directory. If the model file does not exist locally, the system SHALL download it on first use and cache it for subsequent runs.

#### Scenario: First run with no cached model
- **WHEN** the detector is initialized and no model file exists in the cache directory
- **THEN** the system SHALL download the model file, save it to the cache directory, and load it

#### Scenario: Subsequent run with cached model
- **WHEN** the detector is initialized and the model file exists in the cache directory
- **THEN** the system SHALL load the model directly without downloading

### Requirement: Progress reporting
The detector SHALL report progress as a fraction (frames processed / total frames) via a callback function, allowing the caller to update UI progress indicators.

#### Scenario: Progress callback invoked during detection
- **WHEN** detection is running on a clip with 100 frames
- **THEN** the progress callback SHALL be invoked at least once per 10 frames with the current progress fraction

### Requirement: Cancellation support
The detector SHALL check a cancellation flag between frames and stop processing early if cancellation is requested, returning partial results collected so far.

#### Scenario: Detection cancelled mid-clip
- **WHEN** the user cancels detection after 50 of 100 frames have been processed
- **THEN** the detector SHALL stop processing and return results for the 50 processed frames

### Requirement: Expose per-frame phone exclusion zones in detection results

When `exclude_phones` is enabled, the detector SHALL record, for every processed frame, the set of padded phone exclusion zones that were active when that frame's plate detections were filtered. The recorded zones SHALL be the exact `(x, y, w, h)` normalized tuples consumed by the filter for that frame, with no additional padding, clipping, or transformation. The per-frame zone map SHALL be attached to the returned `ClipPlateData` (or an adjacent debug-data field on the same object) keyed by frame number.

#### Scenario: Clip processed with exclude_phones enabled
- **WHEN** `detect_clip()` runs on a clip with `exclude_phones=True` and at least one frame in the clip contains a phone detection
- **THEN** the returned `ClipPlateData` SHALL expose a mapping from frame number to list of `(x, y, w, h)` zone tuples, with an entry for every frame where zones were active (including frames that reuse zones from a previous refresh)

#### Scenario: Clip processed with exclude_phones disabled
- **WHEN** `detect_clip()` runs on a clip with `exclude_phones=False`
- **THEN** the returned `ClipPlateData` SHALL expose an empty phone-zones map

#### Scenario: Clip with no phones detected
- **WHEN** `detect_clip()` runs with `exclude_phones=True` but no frame contains a phone
- **THEN** the returned `ClipPlateData` SHALL expose an empty phone-zones map and plate-filtering behavior SHALL be unchanged from the disabled case

#### Scenario: Single-frame detection
- **WHEN** `detect_frame()` (single-pass) or `detect_frame_tiled()` is called with `exclude_phones=True` and the frame triggers a phone zone refresh
- **THEN** the active zones SHALL be accessible to the caller via a public accessor on `PlateDetector` without altering the returned plate-box list

### Requirement: Zone recording SHALL NOT alter filtering semantics

Recording phone zones for debug purposes SHALL NOT change which plate boxes are returned by `detect_frame`, `detect_frame_tiled`, or `detect_clip`. The set of surviving plate boxes with recording enabled SHALL be identical to the set produced without recording.

#### Scenario: Filter output stability
- **WHEN** `detect_clip()` is run twice on the same clip with the same seed / same frame content — once with zone recording active and once without
- **THEN** the `detections` dict SHALL be identical across both runs

### Requirement: Vertical-position postfilter (always on)
The detector SHALL always apply a per-frame postfilter that removes false-positive detections in the lower half of the frame whenever at least one detection survives in the upper half of the same frame. The filter SHALL operate on normalized coordinates, use the bounding-box center (`cy = box.y + box.h / 2`) for its top/bottom decision, and apply strictly after the existing geometry and phone-zone filters in both `detect_frame` and `detect_frame_tiled`. The split is fixed at `0.5`: a detection with `cy < 0.5` is classified as "upper"; a detection with `cy >= 0.5` is classified as "lower". When at least one upper detection exists, all lower detections SHALL be dropped from the returned list. When no upper detection exists, the list SHALL be returned unchanged. The filter SHALL NOT be configurable — there SHALL be no constructor parameter, instance attribute, method argument, UI toggle, or settings key that enables, disables, or tunes it.

#### Scenario: Upper plate present drops lower plates
- **WHEN** a frame produces at least one surviving box with `cy < 0.5` and one or more boxes with `cy >= 0.5`
- **THEN** every box with `cy >= 0.5` SHALL be removed from the returned list and every box with `cy < 0.5` SHALL be preserved

#### Scenario: No upper plate preserves lower plates
- **WHEN** every surviving box has `cy >= 0.5`
- **THEN** the returned list SHALL be identical to the pre-filter list (no box is dropped)

#### Scenario: No lower plate is a no-op
- **WHEN** every surviving box has `cy < 0.5`
- **THEN** the returned list SHALL be identical to the pre-filter list

#### Scenario: Empty frame is a no-op
- **WHEN** the pre-filter list is empty
- **THEN** the returned list SHALL also be empty

#### Scenario: Box exactly on split line counts as lower
- **WHEN** a frame has one box with `cy=0.25` and one with `cy=0.5` exactly
- **THEN** the box with `cy=0.5` SHALL be dropped (the split line belongs to the bottom half per the `cy >= 0.5` convention) and the box with `cy=0.25` SHALL be preserved

#### Scenario: Phone-zone-eliminated top box does not protect lower boxes
- **WHEN** the only upper-half box was already removed by `_filter_phone_zones`, leaving only lower-half boxes as input to the vertical-position filter
- **THEN** the vertical-position filter SHALL treat the frame as "no upper plate present" and return all lower boxes unchanged

#### Scenario: Filter applied across detect_clip
- **WHEN** `detect_clip` runs across a range of frames, some of which have mixed upper/lower detections and some of which have lower-only detections
- **THEN** the per-frame entries in the returned `ClipPlateData.detections` SHALL reflect the filter applied to each frame individually — mixed frames drop their lower boxes; lower-only frames retain their boxes (subject to the existing temporal filter)

#### Scenario: Phone-zone recording unchanged
- **WHEN** `detect_clip` runs with `exclude_phones=True` on any clip
- **THEN** the `ClipPlateData.phone_zones` map SHALL reflect the same zones that would have been recorded before this change — the vertical-position filter SHALL NOT alter zone recording

#### Scenario: No new public configuration surface
- **WHEN** inspecting the public API of `PlateDetector` (constructor signature, public methods, public attributes) after this change
- **THEN** there SHALL be no new parameter, attribute, or method that controls, disables, or tunes the vertical-position filter — its behavior is fixed at the 0.5 split and always active

### Requirement: Dashboard exclusion filter SHALL be gated on upper-half plate presence

When `exclude_phones` is enabled, the detector SHALL apply the dashboard / phone-zone exclusion filter to a frame only if the post-geometry candidate box list for that same frame contains at least one box whose center lies in the upper half of the frame (`cy = box.y + box.h / 2 < 0.5`, reusing the existing `_VERTICAL_SPLIT_THRESHOLD = 0.5` convention). When no upper-half candidate is present, the dashboard exclusion filter SHALL be skipped for that frame and every post-geometry box SHALL be passed through unchanged to the next stage of the pipeline. The check SHALL be made independently per frame and SHALL apply identically in both `detect_frame` and `detect_frame_tiled`. The order of pipeline stages SHALL remain: model output → `_filter_geometry` → (gated) `_filter_phone_zones` → `_filter_vertical_position`.

#### Scenario: Lower-only frame inside dashboard zone is retained
- **WHEN** a frame's post-geometry candidate list contains only boxes with `cy >= 0.5`, and at least one of those boxes has its center inside an active dashboard exclusion zone
- **THEN** `_filter_phone_zones` SHALL NOT be applied to that frame and the box(es) inside the dashboard zone SHALL be returned in the detection results

#### Scenario: Mixed upper/lower frame still drops dashboard-zone box
- **WHEN** a frame's post-geometry candidate list contains at least one box with `cy < 0.5` AND at least one box with `cy >= 0.5` whose center lies inside an active dashboard exclusion zone
- **THEN** `_filter_phone_zones` SHALL be applied: the dashboard-zone box SHALL be removed before `_filter_vertical_position` runs

#### Scenario: Upper-only frame leaves the filter as a no-op
- **WHEN** a frame's post-geometry candidate list contains only boxes with `cy < 0.5`
- **THEN** `_filter_phone_zones` SHALL be invoked but SHALL have no effect (dashboard zones are constrained to the bottom of the frame and contain no upper-half centers), and the returned list SHALL be identical to the post-geometry list

#### Scenario: Empty post-geometry list is a no-op
- **WHEN** the post-geometry candidate list is empty
- **THEN** `_filter_phone_zones` SHALL be skipped (no upper-half presence) and the returned list SHALL be empty

#### Scenario: exclude_phones disabled
- **WHEN** `exclude_phones=False`
- **THEN** the gate SHALL not change behaviour — `_filter_phone_zones` is already a no-op (no zones are populated), so no upper-half check SHALL be required and the existing pipeline SHALL run as before

#### Scenario: Tiled detection applies the same gate
- **WHEN** `detect_frame_tiled` runs and produces a post-geometry candidate list with no upper-half box
- **THEN** the gate SHALL skip `_filter_phone_zones` for that frame, identically to `detect_frame`

### Requirement: Phone-zone recording SHALL remain frame-independent of the filter gate

Per-frame recording of active dashboard / phone exclusion zones SHALL be unaffected by the new filter gate. `update_phone_zones` SHALL continue to run at the start of every frame regardless of upper-half presence, and `current_phone_zones` together with `ClipPlateData.phone_zones` SHALL continue to expose the active zones for every processed frame on which they were active — including frames where the filter itself was skipped because no upper-half candidate was present. The "Show Dashboard Filter" debug overlay SHALL therefore continue to render zones on every frame where they were detected.

#### Scenario: Zone recorded even when filter is skipped
- **WHEN** `detect_clip()` runs with `exclude_phones=True` on a frame that contains no upper-half candidate but for which `update_phone_zones` populated an active zone
- **THEN** `ClipPlateData.phone_zones[frame_num]` SHALL contain the active zone tuples for that frame, exactly as if the filter had been applied

#### Scenario: Filter-skip does not mutate ClipPlateData.phone_zones cardinality
- **WHEN** the same clip is processed twice — once with this change in place and once with the pre-change always-on filter — using the same model fixture
- **THEN** the set of frame keys present in `ClipPlateData.phone_zones` SHALL be identical across both runs (only `ClipPlateData.detections` may differ, by retaining boxes that were previously dropped)

