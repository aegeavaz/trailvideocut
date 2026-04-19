## ADDED Requirements

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
