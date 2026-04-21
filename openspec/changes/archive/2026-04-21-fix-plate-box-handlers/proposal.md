## Why

Four regressions in the plate-box overlay editor make oriented boxes hard to work with: the rotated outline is drawn distorted (so the visible quadrilateral is not the same as the box the code stores), the eight resize handles appear detached from that distorted outline, the Refine buttons never switch on the first time the user manually adds a plate to a clip that had no plates, and newly added boxes always start axis-aligned even when neighbouring frames carry a non-zero rotation. Together they break the workflow of adding and adjusting manual plates on rotated vehicles.

## What Changes

- Paint the oriented plate outline using the same pixel-space rotation that positions the resize and rotation handles, so the visible quadrilateral stays a true rectangle (preserved 90° corners) and the handles sit exactly on its corners and edge midpoints.
- Make hit-testing of the box body, resize handles, and the rotation handle, plus the resize math itself, consistent with that same pixel-space rotation, so drags on oriented boxes produce rectangles instead of parallelograms.
- Re-evaluate the Refine Clip Plates and Refine Frame Plates buttons whenever the plate set of the current clip/frame changes (add, move, resize, rotate, delete), so adding the first plate on a clip or frame immediately activates both Refine buttons.
- When a manual plate is added — whether via motion projection, nearest-reference clone, or explicit cursor/button placement — inherit the `angle` of the reference box (or the reference used for projection) so the new box matches the surrounding rotation instead of snapping back to axis-aligned.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `plate-overlay-ui`: the existing oriented-rendering, handle-positioning, hit-testing, resize-preserves-rotation, rotation-handle, button-state, and add-manual-box requirements are tightened so rotation math is done in pixel space and so adding a box inherits the reference rotation and refreshes the Refine buttons.

## Impact

- **Code**: `src/trailvideocut/ui/plate_overlay.py` (paint of oriented outline, rotation/resize math, hit-test), `src/trailvideocut/ui/review_page.py` (`_on_add_plate` rotation inheritance, `_on_plate_box_changed` must refresh the frame-button enablement).
- **Data model**: no changes to `PlateBox` shape or to the sidecar format; `angle` is already persisted.
- **Tests**: `tests/` gains targeted unit tests for the overlay's rotated rectangle geometry (outline vs. handle positions must agree), for add-plate rotation inheritance from projection/nearest-reference, and for the Refine-button refresh path after `box_changed`.
- **UX/users**: existing saved plate data is unaffected; users editing oriented boxes will see a correct rectangle instead of a parallelogram and will be able to refine freshly added plates without having to first navigate away and back.
