## MODIFIED Requirements

### Requirement: Add a manual plate box
The system SHALL allow the user to add a new bounding box on the current frame. The new box SHALL be pre-populated with the position and size of the nearest detected plate, searching first backward and then forward in frame order. If no detection exists in any frame, the box SHALL be placed at the mouse cursor position with a default size.

#### Scenario: Add box with prior detection available
- **WHEN** the user triggers "Add plate box" and frame 50 has a detected plate but frames 51-55 do not, and the current frame is 55
- **THEN** a new box SHALL be created at frame 55 with the same position and size as the plate from frame 50, marked as `manual: true`

#### Scenario: Add box with no prior but next detection available
- **WHEN** the user triggers "Add plate box" on frame 10, no frames before 10 have detections, and frame 20 has a detected plate
- **THEN** a new box SHALL be created at frame 10 with the same position and size as the plate from frame 20, marked as `manual: true`

#### Scenario: Add box with no detection in any frame, via right-click
- **WHEN** the user right-clicks on the video overlay to add a plate box and no frames in the current clip have any detections
- **THEN** a new box SHALL be created centered at the mouse cursor position with a default size (15% of frame width, 5% of frame height), marked as `manual: true`

#### Scenario: Add box with no detection in any frame, via button
- **WHEN** the user clicks the "Add Plate" button and no frames in the current clip have any detections
- **THEN** a new box SHALL be created at the center of the frame with a default size (15% of frame width, 5% of frame height), marked as `manual: true`

#### Scenario: Added box is immediately editable
- **WHEN** a manual box is added
- **THEN** the new box SHALL be automatically selected, ready for move/resize
