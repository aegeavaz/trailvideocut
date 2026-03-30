## Why

The plate review workflow has two UX friction points: (1) zooming always scales from the viewport center, forcing the user to pan after every zoom to reach the area of interest — mouse-cursor-centered zoom is the standard expectation in image/video viewers; (2) when adding a manual plate box on a frame with no prior detections, the box appears at a hardcoded center position instead of near the user's cursor or near a detection from an adjacent frame, requiring extra dragging to position it.

## What Changes

- Change the zoom behavior in `VideoPlayer` so the view zooms toward/away from the mouse cursor position, keeping the point under the cursor visually stable.
- Extend the "Add Plate" reference-box logic to also search forward (next frames) when no prior frame has a detection, and fall back to placing the box at the mouse cursor position when no reference exists at all.

## Capabilities

### New Capabilities
- `cursor-centered-zoom`: Zoom in/out keeps the point under the mouse cursor fixed, providing a natural zoom-to-point-of-interest experience.

### Modified Capabilities
- `plate-overlay-ui`: Extend add-plate logic to search next-frame detections as fallback, and place the box at the mouse cursor position when no reference detection exists.

## Impact

- **Code**: Changes to `ui/video_player.py` (zoom transform logic), `ui/plate_overlay.py` (reference search and cursor position), and `ui/review_page.py` (pass cursor position to add-plate flow).
- **Dependencies**: None.
