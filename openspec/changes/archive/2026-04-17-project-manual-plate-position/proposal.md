## Why

When users add a manual plate box on a frame that has no detection, the current behavior clones the x, y, w, h of the nearest reference box verbatim. On moving trail footage this drops the box in the *old* location of the plate, forcing the user to drag it to where the plate actually is now. Projecting the box along the motion observed in recent detections places it close to the true location, reducing manual adjustment.

## What Changes

- Replace the "clone nearest reference box" logic in the manual-plate add path with a motion-aware projection that uses recent detections to extrapolate position (and optionally size) onto the current frame.
- Fall back gracefully: if fewer than two usable reference detections exist, reuse the existing behavior (single-box clone, then cursor placement, then frame-center default).
- The projected box stays marked `manual: true` and is selected on creation, preserving current UX.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `plate-overlay-ui`: the "Add a manual plate box" requirement changes — pre-population is no longer a verbatim clone of the single nearest box but a projection computed from multiple recent detections, with documented fallbacks.

## Impact

- Code: `src/trailvideocut/ui/plate_overlay.py` (reference-box lookup), `src/trailvideocut/ui/review_page.py` (`_on_add_plate`), and a new pure-Python projector module under `src/trailvideocut/plate/` (e.g. `projection.py`) so the math is unit-testable without Qt.
- Tests: new unit tests for the projector; existing overlay/review tests updated to cover the projection path and the unchanged fallbacks.
- No change to `PlateBox`/`ClipPlateData` schema, sidecar format, export pipeline, or detector — this is a pure UX improvement in the add-plate flow.
