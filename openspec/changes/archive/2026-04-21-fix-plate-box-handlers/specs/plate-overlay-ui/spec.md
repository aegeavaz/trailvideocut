## MODIFIED Requirements

### Requirement: Render oriented plate boxes
When a plate box has a non-zero rotation angle, the overlay SHALL render its outline as a rotated quadrilateral (four corner points) rather than an axis-aligned rectangle. The four corners SHALL be computed in the **video pixel coordinate system** (i.e. the box's normalized half-width multiplied by the current video display width, and the normalized half-height multiplied by the current video display height) and rotated by `box.angle` around the box centre in that pixel space, then translated into the overlay's widget coordinates. The rendering SHALL NOT compute rotation in normalized (1x1) coordinates and then scale the rotated corners, because that distorts the rectangle into a parallelogram whenever the video's display width and height differ. Axis-aligned boxes (`angle == 0`) SHALL continue to render as axis-aligned rectangles and remain pixel-identical to the previous behaviour.

#### Scenario: Rotated outline is a true rectangle on non-square videos
- **WHEN** a clip on a video whose display aspect ratio is not 1:1 (e.g. 16:9 or 4:3) has a plate box with `angle = 20°` and the overlay paints
- **THEN** the four drawn outline corners SHALL form a rectangle in widget pixel coordinates (opposite sides equal in length and all interior angles equal to 90° within floating-point tolerance), not a parallelogram

#### Scenario: Rotated outline draw
- **WHEN** the current frame has a plate box with `angle = 20°` and the overlay paints
- **THEN** the outline SHALL be the rotated quadrilateral's four edges in the current coordinate system, and no axis-aligned rectangle SHALL be drawn for that box

#### Scenario: Axis-aligned boxes unchanged
- **WHEN** the current frame has only axis-aligned boxes
- **THEN** the overlay rendering SHALL be visually identical to the pre-feature behaviour

### Requirement: Resize and rotation handles on the rotated plate-aligned rect
For a selected oriented box, the eight resize handles (four corners + four edge midpoints) SHALL be drawn on the **same rotated plate-aligned rectangle** that the outline uses — so the handles always lie exactly on the visible outline. The rotation SHALL be computed in video pixel space (half-widths multiplied by the video display width and half-heights multiplied by the display height before rotation) and the outline and the handle positions SHALL be derived from a single geometry source so they cannot drift. Axis-aligned boxes (`angle == 0`) SHALL place handles at the same positions as before (the rotated rect coincides with the envelope). A ninth, round **rotation handle** SHALL be drawn a short distance above the top-centre edge along the box's local "up" direction (also computed in pixel space); hit-testing for this handle SHALL use a radial tolerance rather than a square bounding region. Hit-testing for the whole box SHALL use the same pixel-space rotated rectangle, not the axis-aligned envelope, so transparent envelope corners do not intercept clicks.

#### Scenario: Handles on rotated corners coincide with outline
- **WHEN** the user selects an oriented box with `angle = 25°` on a non-square video
- **THEN** each of the eight resize handles SHALL be centred exactly on the corresponding corner or edge midpoint of the drawn outline (within rounding tolerance), and the round rotation handle SHALL sit above the top-centre of that outline along the outline's local "up" direction

#### Scenario: Click inside rotated body selects box
- **WHEN** the user clicks a point inside the rotated rectangle but outside its axis-aligned envelope's clear zone
- **THEN** the box SHALL be selected; a click on a transparent envelope corner (outside the rotated rectangle) SHALL NOT select the box

### Requirement: Manual edit of an oriented box preserves its rotation
When the user drags the body or a resize handle of an oriented box via the overlay, the box's `angle` SHALL be preserved. Move SHALL translate only the centre; resize SHALL change only the plate-aligned `(w, h)` by projecting the mouse offset onto the box's local axes **in video pixel space** and then converting the resulting `(w, h)` back to normalized coordinates by dividing by the video display width and height respectively, while keeping the opposite corner/edge reference fixed in widget coordinates. Resize math SHALL NOT use normalized-space unit vectors for the plate's local axes, because on non-square videos that projection distorts the box into a parallelogram.

#### Scenario: Move preserves angle
- **WHEN** the user drags an oriented box (not on a handle) to reposition it
- **THEN** the saved box SHALL have the same `angle`, `w`, `h` as before, with only its centre translated

#### Scenario: Resize preserves angle and rectangular shape on non-square video
- **WHEN** the user drags any resize handle on a selected oriented box with `angle = 20°` on a 16:9 video
- **THEN** on drag release the saved box SHALL still have `angle == 20.0`, the plate-aligned `(w, h)` SHALL be adjusted from the drag, and the four pixel-space corners of the updated box SHALL still form a rectangle (opposite sides equal, interior angles of 90°)

### Requirement: Add a manual plate box
The system SHALL allow the user to add a new bounding box on the current frame. When two or more recent reference detections are available, the new box's position SHALL be computed by projecting the motion of those detections onto the current frame. When fewer than two reference detections are usable, the system SHALL fall back in order: clone the single nearest detection, then place at the mouse cursor position with a default size, then place at the frame center with a default size. In all three detection-aware paths (motion projection, nearest-reference clone, and — if the nearest reference is used to size a cursor/centre placement) the new box's `angle` SHALL be inherited from the nearest reference detection used, so that new manual boxes match the surrounding rotation instead of snapping back to axis-aligned. Only the pure default-size fallback used when no reference detection exists at all SHALL produce `angle == 0.0`. The new box SHALL always be marked `manual: true`, SHALL be clamped to remain fully within the frame (using the axis-aligned envelope of the rotated rectangle), and the system SHALL auto-save all plate data to the sidecar file.

#### Scenario: Projection with two prior detections
- **WHEN** the user triggers "Add plate box" at frame 60, frame 40 has a detected plate at normalized center (0.40, 0.50), and frame 50 has a detected plate at normalized center (0.45, 0.50)
- **THEN** a new box SHALL be created at frame 60 with its normalized center projected along the observed motion (approximately (0.50, 0.50)), using the size of the nearest reference detection, marked as `manual: true`

#### Scenario: Projection inherits rotation from the nearest reference
- **WHEN** the user triggers "Add plate box" at frame 60, prior detections at frame 40 and 50 both have `angle = 15°`, and the nearest reference (frame 50) is chosen for size
- **THEN** the new box SHALL have `angle = 15°`, inherited from the nearest reference

#### Scenario: Projection clamps to frame bounds
- **WHEN** a projected box's center would place its axis-aligned envelope partially outside the frame (e.g., the projected x is 0.98 with a width of 0.15)
- **THEN** the box SHALL be clamped so its envelope remains fully within the normalized range [0, 1] on both axes

#### Scenario: Projection between prior and next detections
- **WHEN** the user triggers "Add plate box" at frame 55, frame 50 has a detected plate, and frame 60 has a detected plate, and no other detections exist
- **THEN** a new box SHALL be created at frame 55 with its position interpolated along the motion between the two detections, marked as `manual: true`

#### Scenario: Projection with only next-side detections
- **WHEN** the user triggers "Add plate box" at frame 10, no frames before 10 have detections, and frames 20 and 30 have detected plates
- **THEN** a new box SHALL be created at frame 10 with its position extrapolated backward from those next-side detections, marked as `manual: true`

#### Scenario: Projection gap exceeds the motion window
- **WHEN** the only reference detections are more than the configured motion window (e.g., 60 frames) away from the current frame
- **THEN** the system SHALL NOT project; it SHALL fall back to cloning the nearest single reference detection (position, size, **and angle**), marked as `manual: true`

#### Scenario: Only one reference detection available inherits its rotation
- **WHEN** the user triggers "Add plate box" and only a single reference detection (with `angle = 12°`) is available in the clip
- **THEN** a new box SHALL be created at the current frame with the same position, size, and `angle = 12°` as that detection, marked as `manual: true`

#### Scenario: Add box with no detection in any frame, via right-click
- **WHEN** the user right-clicks on the video overlay to add a plate box and no frames in the current clip have any detections
- **THEN** a new box SHALL be created centered at the mouse cursor position with a default size (15% of frame width, 5% of frame height), `angle == 0.0`, marked as `manual: true`

#### Scenario: Add box with no detection in any frame, via button
- **WHEN** the user clicks the "Add Plate" button and no frames in the current clip have any detections
- **THEN** a new box SHALL be created at the center of the frame with a default size (15% of frame width, 5% of frame height), `angle == 0.0`, marked as `manual: true`

#### Scenario: Added box is immediately editable
- **WHEN** a manual box is added
- **THEN** the new box SHALL be automatically selected, ready for move/resize

### Requirement: Button state updates on navigation
The system SHALL update the enabled/disabled state of the action buttons (Detect Frame, Clear Clip Plates, Clear Frame Plates, Refine Clip Plates, Refine Frame Plates, Preview Blur) when the user navigates between clips or seeks to a different frame position, **and whenever the plate set of the current clip or frame changes through any overlay-driven edit** — including adding, moving, resizing, rotating, or deleting a plate box. Refresh of the enablement state SHALL NOT depend on the user leaving and re-entering the current frame; adding the very first plate on a clip or frame SHALL immediately activate the Refine Clip Plates, Refine Frame Plates, Clear Clip Plates, and Clear Frame Plates buttons.

#### Scenario: User navigates to clip with plate data
- **WHEN** the user selects a clip that has plate data
- **THEN** "Detect Frame" and "Clear Clip Plates" become enabled, and "Clear Frame Plates" is enabled only if the current frame has plates

#### Scenario: User seeks to frame without plates
- **WHEN** the user seeks to a frame with no detected plates (within a clip that has plate data)
- **THEN** "Clear Frame Plates" becomes disabled while "Detect Frame" and "Clear Clip Plates" remain enabled

#### Scenario: Adding the first plate to a clip enables refine buttons
- **WHEN** the selected clip has no plate detections anywhere, and the user adds a manual plate box on the current frame
- **THEN** "Refine Clip Plates" and "Refine Frame Plates" SHALL become enabled immediately (without requiring the user to change frames), along with "Clear Clip Plates" and "Clear Frame Plates"

#### Scenario: Adding a plate on a frame that previously had none
- **WHEN** the clip already has plates on other frames but the current frame has none, and the user adds a manual plate box on the current frame
- **THEN** "Refine Frame Plates" and "Clear Frame Plates" SHALL become enabled immediately

#### Scenario: Deleting the last plate on a frame
- **WHEN** the current frame has one plate and the user deletes it (via canvas or chip)
- **THEN** "Refine Frame Plates" and "Clear Frame Plates" SHALL become disabled immediately while "Refine Clip Plates" and "Clear Clip Plates" remain enabled as long as other frames in the clip still have plates

## ADDED Requirements

### Requirement: Blur-preview tiles follow the rotated plate
When the Preview Blur toggle is on and the current frame contains an oriented plate box (`angle != 0`), the preview tile the overlay renders SHALL cover the **AABB envelope** of that rotated rectangle, not the plate-aligned `(x, y, w, h)` rectangle. The cropped pixels SHALL be read from the envelope region of the blurred frame produced by `apply_blur_to_frame`, so the blurred pixels inside the rotated plate and the untouched pixels inside the envelope's outer triangles are both present in the tile and register at their true video positions. Axis-aligned boxes (`angle == 0`) SHALL continue to use the plate-aligned rectangle (envelope and plate-aligned rect coincide in that case), preserving the pre-feature behaviour pixel-for-pixel.

#### Scenario: Oriented plate shows a rotated blurred region
- **WHEN** the user enables Preview Blur on a frame containing a plate with `angle = 20°`
- **THEN** the overlay SHALL render a blur tile whose rectangular footprint equals the box's AABB envelope and whose blurred pixels lie inside the rotated plate quadrilateral (the envelope's outer triangles SHALL show the untouched video pixels so the blur appears as a rotated patch, not an axis-aligned square)

#### Scenario: Axis-aligned plate preview is unchanged
- **WHEN** the user enables Preview Blur on a frame whose plates are all axis-aligned
- **THEN** the blur tile footprint and pixel content SHALL be identical to the pre-feature behaviour
