## Why

The dashboard exclusion filter (`_filter_phone_zones`) currently runs on every frame whenever `exclude_phones` is enabled. In practice this is too aggressive: when a frame contains no upper-half plates at all, there is no contextual evidence that we're filming a real scene with another vehicle ahead — so dropping a lower-half plate just because it overlaps the dashboard zone risks discarding a legitimate detection (e.g. a bike directly in front of us, low in the frame). By gating the filter on "at least one upper-half plate present in the same frame", we keep the noise-suppression benefit when the scene context confirms it is a road scene, and avoid false-negative drops in close-quarter or stop-and-go footage where the only plate is in the lower half.

## What Changes

- In `PlateDetector.detect_frame` and `PlateDetector.detect_frame_tiled`, gate the call to `_filter_phone_zones` on a per-frame check: only apply it when at least one box in the post-geometry, pre-phone-zone candidate list has its center in the upper half (`cy < 0.5`, reusing the existing `_VERTICAL_SPLIT_THRESHOLD` constant).
- When no upper-half candidate is present, skip `_filter_phone_zones` entirely and pass the post-geometry boxes straight to the existing `_filter_vertical_position` (which becomes a no-op, since there is no upper-half box to trigger lower-half pruning).
- **Recording is unchanged**: `update_phone_zones` still runs at the start of each frame, and `current_phone_zones` / `ClipPlateData.phone_zones` continue to expose the active zones for every processed frame regardless of whether the filter was applied. The "Show Dashboard Filter" overlay therefore continues to render zones on every frame where they exist.
- The existing always-on vertical-position postfilter (`_filter_vertical_position`) is unchanged in semantics and ordering — it still runs last.

This is a behavioural change in detector output for frames that previously had a lower-half plate inside a dashboard zone AND no upper-half plate. Those plates will now be retained instead of dropped.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `plate-detector`: the existing "Expose per-frame phone exclusion zones in detection results" requirement is unchanged in behaviour, but the filtering semantics it depends on are tightened by a new sibling requirement that gates `_filter_phone_zones` on the upper-half-presence condition. Spec deltas: add a new requirement describing the per-frame gate, and explicitly preserve the recording / no-mutation invariants of the existing requirements.

## Impact

- Code:
  - `src/trailvideocut/plate/detector.py` — change the filter pipeline order in both `detect_frame` and `detect_frame_tiled`. Likely shape: introduce a small helper `_should_apply_phone_zone_filter(boxes)` (or inline the predicate using `_VERTICAL_SPLIT_THRESHOLD`) and call it before `_filter_phone_zones`.
- Tests:
  - `tests/test_plate_detector.py` — add new scenarios under a `TestDashboardFilterUpperPlateGate` (or extend `TestPlateDetectorVerticalPositionFilter`) covering: (a) lower-only frame retains dashboard-zone box, (b) mixed upper/lower frame still has dashboard-zone box dropped, (c) upper-only frame is a no-op, (d) recording invariant: zones still recorded even when filter was skipped.
  - Existing `test_zone_recording_does_not_alter_detections` and the vertical-position-filter scenarios may need to be reviewed for any frame fixture that incidentally exercised the now-gated path.
- Specs:
  - `openspec/specs/plate-detector/spec.md` — add a new requirement under the existing detector spec covering the new gate; keep existing requirements intact.
- No UI surface change, no new constructor parameter, no new sidecar field. The "Exclude Dashboard" / "Show Dashboard Filter" checkboxes keep their current semantics; only the in-detector application of the zone filter changes.
