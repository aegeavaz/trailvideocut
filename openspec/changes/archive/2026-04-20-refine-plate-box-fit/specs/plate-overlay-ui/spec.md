## ADDED Requirements

### Requirement: Render oriented plate boxes
When a plate box has a non-zero rotation angle, the overlay SHALL render its outline as a rotated quadrilateral (four corner points) rather than an axis-aligned rectangle. The quadrilateral's corners SHALL be computed from the box's normalized `(centre_x, centre_y, width, height, angle)` mapped to the current video widget coordinate system. Axis-aligned boxes (`angle == 0`) SHALL continue to render as axis-aligned rectangles.

#### Scenario: Rotated outline draw
- **WHEN** the current frame has a plate box with `angle = 20°` and the overlay paints
- **THEN** the outline SHALL be the rotated quadrilateral's four edges in the current coordinate system, and no axis-aligned rectangle SHALL be drawn for that box

#### Scenario: Axis-aligned boxes unchanged
- **WHEN** the current frame has only axis-aligned boxes
- **THEN** the overlay rendering SHALL be visually identical to the pre-feature behaviour

### Requirement: Resize and rotation handles on the rotated plate-aligned rect
For a selected oriented box, the eight resize handles (four corners + four edge midpoints) SHALL be drawn on the **rotated plate-aligned rectangle** itself — not on its axis-aligned envelope. Axis-aligned boxes (`angle == 0`) SHALL place handles at the same positions as before (the rotated rect coincides with the envelope). A ninth, round **rotation handle** SHALL be drawn a short distance above the top-centre edge along the box's local "up" direction; hit-testing for this handle SHALL use a radial tolerance rather than a square bounding region. Hit-testing for the whole box SHALL use the rotated rectangle, not the envelope, so transparent envelope corners do not intercept clicks.

#### Scenario: Handles on rotated corners
- **WHEN** the user selects an oriented box with `angle = 25°`
- **THEN** eight resize handles SHALL be drawn at the four rotated corners and four edge midpoints of the plate-aligned rectangle, and a round rotation handle SHALL be drawn above the top-centre of that rectangle

#### Scenario: Click inside rotated body selects box
- **WHEN** the user clicks a point inside the rotated rectangle but outside its axis-aligned envelope's clear zone
- **THEN** the box SHALL be selected; a click on a transparent envelope corner (outside the rotated rectangle) SHALL NOT select the box

### Requirement: Manual edit of an oriented box preserves its rotation
When the user drags the body or a resize handle of an oriented box via the overlay, the box's `angle` SHALL be preserved. Move SHALL translate only the centre; resize SHALL change only the plate-aligned `(w, h)` by projecting the mouse offset onto the box's local axes while keeping the opposite corner/edge reference fixed in widget coordinates.

#### Scenario: Move preserves angle
- **WHEN** the user drags an oriented box (not on a handle) to reposition it
- **THEN** the saved box SHALL have the same `angle`, `w`, `h` as before, with only its centre translated

#### Scenario: Resize preserves angle
- **WHEN** the user drags any resize handle on a selected oriented box with `angle = 20°`
- **THEN** on drag release the saved box SHALL still have `angle == 20.0`, with the plate-aligned `(w, h)` adjusted from the drag

### Requirement: Rotation handle drag changes the angle only
Dragging the rotation handle SHALL update the box's `angle` such that the handle tracks the mouse position's angle relative to the box's centre; `w`, `h`, and centre SHALL NOT change.

#### Scenario: Rotating the handle
- **WHEN** the user drags the rotation handle from above the top-centre to a point 90° around the centre
- **THEN** the saved box's `angle` SHALL reflect the new orientation (±1° tolerance) and its `(w, h, centre)` SHALL equal the pre-drag values

## MODIFIED Requirements

### Requirement: New action buttons in plate controls panel
The system SHALL display the Plate Detection group box occupying the full width of the bottom section (no longer sharing horizontal space with a clip details panel). The bottom section SHALL have a fixed height of 190px. All action buttons SHALL be in a single row. The settings, plate chips, and controls rows SHALL remain functionally identical but benefit from the additional horizontal space. The action row SHALL include "Refine Clip Plates" and "Refine Frame Plates" buttons, placed adjacent to their matching "Clear Clip Plates" / "Clear Frame Plates" buttons.

#### Scenario: Button layout
- **WHEN** the review page is displayed with plate detection controls visible
- **THEN** the Plate Detection group box SHALL span the full width of the bottom section, with a single row containing "Detect Plates", "Detect Frame", "Add Plate", "Refine Clip Plates", "Refine Frame Plates", "Clear Clip Plates", "Clear Frame Plates", and "Show Plates" checkbox

#### Scenario: Buttons enabled after detection
- **WHEN** plate detection has completed for at least one clip
- **THEN** "Detect Frame" is enabled if a clip is selected and video is loaded; "Clear Clip Plates" and "Refine Clip Plates" are enabled if the selected clip has at least one plate box on any frame; "Clear Frame Plates" and "Refine Frame Plates" are enabled if the current frame has at least one plate box

#### Scenario: Buttons disabled initially
- **WHEN** the review page is first loaded with no plate data
- **THEN** all new action buttons SHALL be disabled, including "Refine Clip Plates" and "Refine Frame Plates"

#### Scenario: Bottom section height
- **WHEN** the ReviewPage is displayed
- **THEN** the bottom section containing the Plate Detection panel SHALL have a fixed height of 190px
