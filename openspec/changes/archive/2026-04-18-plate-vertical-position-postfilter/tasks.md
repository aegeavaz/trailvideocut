## 1. Tests First (TDD)

- [x] 1.1 Add a new `TestPlateDetectorVerticalPositionFilter` test class to `tests/test_plate_detector.py`.
- [x] 1.2 Write failing test: filter drops lower boxes when at least one upper box exists (box with `cy=0.3` kept, box with `cy=0.7` dropped).
- [x] 1.3 Write failing test: filter is a no-op when only lower boxes exist (all boxes retained).
- [x] 1.4 Write failing test: filter is a no-op when only upper boxes exist (all boxes retained).
- [x] 1.5 Write failing test: filter on empty box list returns empty list.
- [x] 1.6 Write failing test: box with `cy` exactly equal to `0.5` is classified as lower and dropped when an upper box is present; a lone `cy=0.5` box with no upper companion is retained.
- [x] 1.7 Write failing test: when wired into `detect_frame`, a phone-zone-eliminated upper box does NOT trigger dropping of lower boxes (compose-with-phone-filter test). Patch `_parse_output` and `update_phone_zones` to avoid needing a real model.
- [x] 1.8 Write failing test: `detect_clip` produces per-frame entries where mixed frames are pruned and lower-only frames are untouched.
- [x] 1.9 Write failing test: `PlateDetector.__init__` signature has no new parameters (e.g. use `inspect.signature(PlateDetector.__init__)` to assert the parameter set is unchanged from the pre-change baseline).
- [x] 1.10 Run full test file; confirm only the new tests fail and existing tests still pass.

## 2. Detector Changes

- [x] 2.1 Add a module-level constant in `src/trailvideocut/plate/detector.py` — e.g. `_VERTICAL_SPLIT_THRESHOLD = 0.5` — near the other module-level constants.
- [x] 2.2 Implement `_filter_vertical_position(self, boxes: list[PlateBox]) -> list[PlateBox]` in the "Post-detection filters" section, mirroring the style of `_filter_phone_zones`. It SHALL:
  - Return `boxes` unchanged when the list is empty.
  - Classify each box by `cy = box.y + box.h / 2` as upper (`cy < _VERTICAL_SPLIT_THRESHOLD`) or lower (`cy >= _VERTICAL_SPLIT_THRESHOLD`).
  - If no upper box exists, return `boxes` unchanged.
  - Otherwise return only the upper boxes.
- [x] 2.3 Wire the new filter as the final step in `detect_frame` (after `_filter_phone_zones`) — e.g. `return self._filter_vertical_position(self._filter_phone_zones(boxes))`.
- [x] 2.4 Wire the new filter identically in `detect_frame_tiled` after `_filter_phone_zones`.
- [x] 2.5 Confirm `detect_clip` picks up the filter transparently (no code change needed since it calls `detect_frame` / `detect_frame_tiled`).
- [x] 2.6 Do NOT modify `PlateDetector.__init__` signature, stored attributes, or any caller — the filter has no configuration.
- [x] 2.7 Run the test file again; all tests from step 1 SHALL pass and all pre-existing detector tests SHALL still pass.

## 3. Regression Sweep

- [x] 3.1 Run the full test suite (`pytest`) and inspect any failures.
- [x] 3.2 For each pre-existing failure caused by this change, determine whether the failing test was relying on lower-half-only false-positive behavior. If so, update the test expectation; if the test represents a real requirement, re-open the design to reconsider an escape hatch.
- [x] 3.3 Confirm zero unintended regressions before proceeding.

## 4. Manual Verification

- [x] 4.1 Launch the app, load a clip known to produce bottom-half false positives, run detection, and confirm the dashboard-area false positives are gone when real plates are visible up-top.
- [x] 4.2 Load a clip where the only visible plate is genuinely in the lower half (if available) and confirm that plate is still detected (since there is no upper-half box to trigger the drop).
- [x] 4.3 Verify the existing phone-zone filter and temporal filter still function correctly (no crashes, reasonable output in the review page).

## 5. Housekeeping

- [x] 5.1 Update any detector docstring / module-level comment that enumerates the postfilter stages so the order `geometry → phone-zones → vertical-position` is documented.
- [x] 5.2 Run `openspec validate plate-vertical-position-postfilter --strict` and confirm it passes.
- [x] 5.3 Commit with message `Drop lower-half plates when upper-half detection present (openspec: plate-vertical-position-postfilter)` matching the repository's commit-message convention.
