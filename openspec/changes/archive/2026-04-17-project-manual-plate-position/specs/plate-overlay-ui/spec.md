## MODIFIED Requirements

### Requirement: Add a manual plate box
The system SHALL allow the user to add a new bounding box on the current frame. When two or more recent reference detections are available, the new box's position SHALL be computed by projecting the motion of those detections onto the current frame. When fewer than two reference detections are usable, the system SHALL fall back in order: clone the single nearest detection, then place at the mouse cursor position with a default size, then place at the frame center with a default size. The new box SHALL always be marked `manual: true`, SHALL be clamped to remain fully within the frame, and the system SHALL auto-save all plate data to the sidecar file.

#### Scenario: Projection with two prior detections
- **WHEN** the user triggers "Add plate box" at frame 60, frame 40 has a detected plate at normalized center (0.40, 0.50), and frame 50 has a detected plate at normalized center (0.45, 0.50)
- **THEN** a new box SHALL be created at frame 60 with its normalized center projected along the observed motion (approximately (0.50, 0.50)), using the size of the nearest reference detection, marked as `manual: true`

#### Scenario: Projection clamps to frame bounds
- **WHEN** a projected box's center would place the box partially outside the frame (e.g., the projected x is 0.98 with a width of 0.15)
- **THEN** the box SHALL be clamped so it remains fully within the normalized range [0, 1] on both axes

#### Scenario: Projection between prior and next detections
- **WHEN** the user triggers "Add plate box" at frame 55, frame 50 has a detected plate, and frame 60 has a detected plate, and no other detections exist
- **THEN** a new box SHALL be created at frame 55 with its position interpolated along the motion between the two detections, marked as `manual: true`

#### Scenario: Projection with only next-side detections
- **WHEN** the user triggers "Add plate box" at frame 10, no frames before 10 have detections, and frames 20 and 30 have detected plates
- **THEN** a new box SHALL be created at frame 10 with its position extrapolated backward from those next-side detections, marked as `manual: true`

#### Scenario: Projection gap exceeds the motion window
- **WHEN** the only reference detections are more than the configured motion window (e.g., 60 frames) away from the current frame
- **THEN** the system SHALL NOT project; it SHALL fall back to cloning the nearest single reference detection, marked as `manual: true`

#### Scenario: Only one reference detection available
- **WHEN** the user triggers "Add plate box" and only a single reference detection is available in the clip
- **THEN** a new box SHALL be created at the current frame with the same position and size as that detection, marked as `manual: true`

#### Scenario: Add box with no detection in any frame, via right-click
- **WHEN** the user right-clicks on the video overlay to add a plate box and no frames in the current clip have any detections
- **THEN** a new box SHALL be created centered at the mouse cursor position with a default size (15% of frame width, 5% of frame height), marked as `manual: true`

#### Scenario: Add box with no detection in any frame, via button
- **WHEN** the user clicks the "Add Plate" button and no frames in the current clip have any detections
- **THEN** a new box SHALL be created at the center of the frame with a default size (15% of frame width, 5% of frame height), marked as `manual: true`

#### Scenario: Added box is immediately editable
- **WHEN** a manual box is added
- **THEN** the new box SHALL be automatically selected, ready for move/resize
