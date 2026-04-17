## ADDED Requirements

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
