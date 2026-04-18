## ADDED Requirements

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
