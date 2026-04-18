## Why

Plate detection still produces a large number of false positives in the lower half of the frame — typically dashboard reflections, steering-wheel text, or foreground noise. In practice, whenever a genuine license plate is visible ahead of the vehicle, it falls in the upper half of the frame (road / other vehicles in the distance), while the lower half for the same frame usually contains only noise. We can exploit this asymmetry as a cheap, deterministic postfilter: "if a frame has at least one plate detection in the top half, any simultaneous detections in the bottom half are almost certainly false and should be dropped."

This avoids the cost and complexity of retraining the model or raising the confidence threshold globally, which would also suppress legitimate distant plates.

## What Changes

- Add a per-frame postfilter step in `PlateDetector` that, when at least one surviving detection has its bounding-box center in the upper half of the frame (`cy < 0.5`), drops all other detections whose centers fall in the lower half (`cy >= 0.5`).
- The filter SHALL always be active — no configuration, no constructor flag, no UI toggle, no threshold parameter. The 50% split is hardcoded.
- The filter SHALL be applied AFTER existing geometry and phone-zone filters and BEFORE results are returned from `detect_frame` / `detect_frame_tiled`, so it composes cleanly with `detect_clip` and temporal filtering.
- The filter SHALL be a no-op when the frame has zero top-half detections or zero bottom-half detections — i.e. it only removes boxes when both regions are simultaneously populated.
- Add unit tests covering: no top-half detections (keep all), no bottom-half detections (keep all), mixed frame (drop bottom), empty list, box center exactly on the 0.5 line, composition with `_filter_phone_zones`, and `detect_clip` integration.

## Capabilities

### New Capabilities
- None. This change extends an existing capability.

### Modified Capabilities
- `plate-detector`: adds a new always-on filtering requirement for vertical-position-based postfiltering. Existing requirements (confidence threshold, phone-zone filter, zone recording, detection semantics) are unchanged.

## Impact

- Code:
  - `src/trailvideocut/plate/detector.py` — new `_filter_vertical_position()` method, wired into `detect_frame` and `detect_frame_tiled`. No constructor changes.
  - `tests/test_plate_detector.py` — new `TestPlateDetectorVerticalPositionFilter` test class.
- APIs: none changed. `PlateDetector.__init__` signature is unchanged.
- UI: no changes — filter is not user-configurable.
- Dependencies: none.
- Behavior change: this is NOT backwards-compatible for callers who were relying on lower-half detections being returned alongside upper-half ones. Tests and downstream code that assume every model-produced box survives the filters will need to be updated if they encountered this case. In practice this only affects false positives, so the risk is low, but the change in observable output is why this is called out explicitly.
- Performance: O(n) additional pass per frame over already-filtered boxes; negligible.
