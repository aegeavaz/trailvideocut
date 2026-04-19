## 1. Add failing tests for the new gate (TDD)

- [x] 1.1 In `tests/test_plate_detector.py`, add a new test class `TestDashboardFilterUpperPlateGate` (modelled on `TestPlateDetectorVerticalPositionFilter`) with the following scenarios. Use the same `_make_detector(exclude_phones=True)` helper plus a small fixture that injects a known set of `_phone_zones` directly (bypass `update_phone_zones` to keep the test fast and deterministic):
  - `test_lower_only_frame_keeps_box_inside_dashboard_zone`: post-geometry list is `[box at cy=0.9 inside zone]` → `_filter_phone_zones` is NOT applied → box is returned.
  - `test_mixed_upper_lower_drops_dashboard_box_then_drops_lower_via_vertical_filter`: post-geometry list is `[upper box at cy=0.3, lower box at cy=0.9 inside zone]` → `_filter_phone_zones` IS applied → lower box dropped → vertical filter is a no-op on the remaining upper box.
  - `test_upper_only_frame_is_noop`: post-geometry list is `[upper box at cy=0.2]` → `_filter_phone_zones` runs but removes nothing → upper box returned.
  - `test_empty_post_geometry_is_noop`: post-geometry list is `[]` → returned list is `[]`.
  - `test_tiled_path_applies_same_gate`: drive the same lower-only / dashboard-zone scenario through `detect_frame_tiled` with the model patched to emit a single lower-half box → result still contains the lower box.
- [x] 1.2 In the same test class, add `test_should_apply_phone_zone_filter_predicate_uses_split_threshold`: import `_VERTICAL_SPLIT_THRESHOLD` from `trailvideocut.plate.detector`, verify the new private method `_should_apply_phone_zone_filter` returns `True` for any list with a box at `cy = _VERTICAL_SPLIT_THRESHOLD - 1e-6` and `False` for an empty list / a list with all boxes at `cy = _VERTICAL_SPLIT_THRESHOLD`.
- [x] 1.3 Add `test_zone_recording_unchanged_when_filter_skipped` (or extend `TestPlateDetectorPhoneZoneRecording`): drive `detect_clip` against a clip whose only frame produces a single lower-half box AND a populated `_phone_zones` list (via patching `detect_phones`). Assert: (a) the box is preserved in `result.detections[frame_num]` (filter was skipped), and (b) `result.phone_zones[frame_num]` still contains the active zone tuples (recording was not skipped).
- [x] 1.4 Run `.venv/bin/python -m pytest tests/test_plate_detector.py::TestDashboardFilterUpperPlateGate -v` and confirm every new test FAILS against the current always-on `_filter_phone_zones`. Capture output as evidence the tests target the right behaviour. **(3 of 7 failed: predicate test, lower-only retention, tiled gate. The other 4 — mixed-frame, upper-only, empty, recording — were structurally satisfied without the gate; they lock in invariants that must continue to hold.)**

## 2. Implement the gate in the detector

- [x] 2.1 In `src/trailvideocut/plate/detector.py`, add a new private method on `PlateDetector`:
  ```python
  def _should_apply_phone_zone_filter(self, boxes: list[PlateBox]) -> bool:
      """Apply the dashboard exclusion filter only when the same frame has at
      least one upper-half candidate (cy < _VERTICAL_SPLIT_THRESHOLD).
      Reuses the same threshold as _filter_vertical_position by design.
      """
      return any((b.y + b.h / 2) < _VERTICAL_SPLIT_THRESHOLD for b in boxes)
  ```
  Place it adjacent to `_filter_phone_zones` to keep filter-related code grouped.
- [x] 2.2 In `detect_frame`, replace the unconditional `boxes = self._filter_phone_zones(boxes)` with:
  ```python
  if self._should_apply_phone_zone_filter(boxes):
      boxes = self._filter_phone_zones(boxes)
  ```
- [x] 2.3 In `detect_frame_tiled`, replace the unconditional `all_boxes = self._filter_phone_zones(all_boxes)` with the analogous gated call.
- [x] 2.4 Update the comment block above `_filter_geometry` ("Applied per frame, in order: geometry -> phone-zones -> vertical-position. Earlier per-box filters run first; the vertical-position filter is frame-level and needs to see the set after phone-zone elimination.") to describe the new gate, e.g. "Applied per frame, in order: geometry -> phone-zones (gated on upper-half presence) -> vertical-position".

## 3. Validate

- [x] 3.1 Run `.venv/bin/python -m pytest tests/test_plate_detector.py -v` and confirm all tests in `TestDashboardFilterUpperPlateGate` now PASS. (7/7 green.)
- [x] 3.2 Run `.venv/bin/python -m pytest tests/test_plate_detector.py -v` again to confirm `TestPlateDetectorPhoneZoneRecording`, `TestPlateDetectorVerticalPositionFilter`, and `TestTemporalFilterPreservesPhoneZones` all still pass. (All 48 tests in the file pass; recording invariant green.)
- [x] 3.3 Run the full test suite `.venv/bin/python -m pytest` and confirm no regressions elsewhere. (483 passed, 11 skipped, 0 failed.)
- [x] 3.4 Run `openspec validate gate-dashboard-filter-on-upper-plate --strict` and resolve any warnings/errors. (Valid.)
- [x] 3.5 Manually re-run plate detection in the Review page on a clip that previously had legitimate lower-only plates being eaten by the dashboard filter; confirm those plates now appear in the detection results, and that the "Show Dashboard Filter" overlay still renders zones on every frame where they were detected. _(User-verified.)_
