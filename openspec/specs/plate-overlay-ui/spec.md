## ADDED Requirements

### Requirement: Display plate bounding boxes on video
The system SHALL render rectangular bounding boxes over the video player for all detected plates on the currently displayed frame. Boxes SHALL be drawn as colored semi-transparent rectangles with visible borders.

#### Scenario: Frame with detected plates
- **WHEN** the video player displays a frame that has plate detections
- **THEN** bounding boxes SHALL be drawn at the correct positions over the video, scaled to match the current widget size

#### Scenario: Frame with no detections
- **WHEN** the video player displays a frame with no plate detections
- **THEN** no bounding boxes SHALL be displayed

#### Scenario: Video widget resized
- **WHEN** the user resizes the application window
- **THEN** bounding boxes SHALL reposition and rescale to match the new video display area

### Requirement: Select a plate box
The system SHALL allow the user to click on a displayed bounding box to select it. A selected box SHALL be visually distinguished (e.g., highlighted border, resize handles visible).

#### Scenario: Click on a plate box
- **WHEN** the user clicks inside a displayed bounding box
- **THEN** that box SHALL become selected and display resize handles at its corners and edges

#### Scenario: Click outside all boxes
- **WHEN** the user clicks on the video area outside any bounding box
- **THEN** any currently selected box SHALL be deselected

#### Scenario: Multiple overlapping boxes
- **WHEN** the user clicks in an area where multiple boxes overlap
- **THEN** the topmost (smallest area) box SHALL be selected

### Requirement: Move a selected plate box
The system SHALL allow the user to drag a selected bounding box to reposition it within the video frame. The moved position SHALL be saved back to the detection data in normalized coordinates.

#### Scenario: Drag a selected box
- **WHEN** the user clicks and drags inside a selected bounding box (not on a resize handle)
- **THEN** the box SHALL follow the mouse cursor and update its stored position on release

#### Scenario: Drag beyond video boundary
- **WHEN** the user drags a box past the edge of the video display area
- **THEN** the box SHALL be clamped to remain fully within the video boundaries

### Requirement: Resize a selected plate box
The system SHALL display resize handles on a selected box. Dragging a handle SHALL resize the box from that edge or corner. The resized dimensions SHALL be saved in normalized coordinates.

#### Scenario: Drag a corner handle
- **WHEN** the user drags a corner resize handle of a selected box
- **THEN** the box SHALL resize from that corner while the opposite corner remains fixed

#### Scenario: Minimum box size
- **WHEN** the user resizes a box to be very small
- **THEN** the box SHALL enforce a minimum size of 10x10 pixels at the current display scale

### Requirement: Delete a selected plate box
The system SHALL allow the user to delete a selected bounding box by pressing the Delete or Backspace key. The deletion SHALL remove the box from the detection data for that frame.

#### Scenario: Delete a selected box
- **WHEN** a box is selected and the user presses Delete
- **THEN** the box SHALL be removed from the current frame's detection data and disappear from the overlay

#### Scenario: Delete with no selection
- **WHEN** no box is selected and the user presses Delete
- **THEN** all plates on the current frame SHALL be cleared (equivalent to "Clear Frame Plates" button)

### Requirement: Add a manual plate box
The system SHALL allow the user to add a new bounding box on the current frame. The new box SHALL be pre-populated with the position and size of the nearest detected plate, searching first backward and then forward in frame order. If no detection exists in any frame, the box SHALL be placed at the mouse cursor position with a default size. After adding the box, the system SHALL auto-save all plate data to the sidecar file.

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

### Requirement: Display plate data persistence status
The system SHALL display a visual indicator in the plate controls area showing whether saved plate data was loaded from disk for the current video.

#### Scenario: Plates loaded from disk
- **WHEN** plate data is successfully loaded from a sidecar file
- **THEN** a status label SHALL display "Plates loaded from disk" or similar message

#### Scenario: No saved plates
- **WHEN** no sidecar file exists or plate data is empty
- **THEN** no persistence status indicator SHALL be displayed

### Requirement: Clear saved plates button
The system SHALL provide a "Clear Saved Plates" button in the plate controls area. The button SHALL be enabled only when plate data exists (in memory or on disk).

#### Scenario: Click clear saved plates
- **WHEN** the user clicks "Clear Saved Plates"
- **THEN** the system SHALL delete the sidecar file, clear in-memory plate data, hide the plate overlay, and update the status indicator

#### Scenario: Button disabled when no data
- **WHEN** no plate data exists in memory and no sidecar file exists on disk
- **THEN** the "Clear Saved Plates" button SHALL be disabled

### Requirement: New action buttons in plate controls panel
The system SHALL add a second button row in the Plate Detection group box containing "Detect Frame", "Clear Clip Plates", and "Clear Frame Plates" buttons. The buttons SHALL follow the same visual style as existing plate controls.

#### Scenario: Button layout
- **WHEN** the review page is displayed with plate detection controls visible
- **THEN** a second row of buttons appears below the existing "Detect Plates / Add Plate / Show Plates" row, containing "Detect Frame", "Clear Clip Plates", and "Clear Frame Plates" buttons

#### Scenario: Buttons enabled after detection
- **WHEN** plate detection has completed for at least one clip
- **THEN** "Detect Frame" is enabled if a clip is selected and video is loaded, "Clear Clip Plates" is enabled if the selected clip has plate data, and "Clear Frame Plates" is enabled if the current frame has plate boxes

#### Scenario: Buttons disabled initially
- **WHEN** the review page is first loaded with no plate data
- **THEN** all three new buttons SHALL be disabled

### Requirement: Button state updates on navigation
The system SHALL update the enabled/disabled state of the new buttons when the user navigates between clips or seeks to a different frame position.

#### Scenario: User navigates to clip with plate data
- **WHEN** the user selects a clip that has plate data
- **THEN** "Detect Frame" and "Clear Clip Plates" become enabled, and "Clear Frame Plates" is enabled only if the current frame has plates

#### Scenario: User seeks to frame without plates
- **WHEN** the user seeks to a frame with no detected plates (within a clip that has plate data)
- **THEN** "Clear Frame Plates" becomes disabled while "Detect Frame" and "Clear Clip Plates" remain enabled

### Requirement: Delete/Backspace keyboard shortcut dual behavior
The Delete and Backspace keys SHALL delete the currently selected plate box if one is selected. If no plate box is selected, the keys SHALL clear all plates on the current frame (equivalent to the "Clear Frame Plates" button).

#### Scenario: Delete key with plate selected
- **WHEN** a plate box is selected and the user presses Delete or Backspace
- **THEN** only the selected plate box is removed

#### Scenario: Delete key with no plate selected
- **WHEN** no plate box is selected and the user presses Delete or Backspace
- **THEN** all plates on the current frame are cleared

### Requirement: Per-plate blur strength slider on selection
When a plate bounding box is selected in the overlay, the review page SHALL display a blur strength slider (range 0.0 to 1.0) that controls the `blur_strength` value for that specific plate. Changes to the slider SHALL update the plate data and trigger a save.

#### Scenario: User selects a plate and adjusts blur strength
- **WHEN** the user selects a detected plate box and moves the blur strength slider to 0.6
- **THEN** the plate's `blur_strength` SHALL be updated to 0.6 and the change SHALL be persisted to the sidecar file

#### Scenario: No plate selected hides the slider
- **WHEN** no plate box is selected in the overlay
- **THEN** the blur strength slider SHALL be hidden or disabled

#### Scenario: Switching between plates updates slider value
- **WHEN** the user selects plate A (blur_strength=0.3) then selects plate B (blur_strength=0.8)
- **THEN** the slider SHALL update to reflect each plate's current blur_strength value

### Requirement: Blur strength visual indicator on plate overlay
The overlay SHALL display the blur strength value as a small label on each plate box when blur strength differs from the default (1.0), providing visual feedback about per-plate blur settings.

#### Scenario: Plate with non-default blur strength shows label
- **WHEN** a plate has `blur_strength=0.5`
- **THEN** the overlay SHALL display "50%" near the plate box

#### Scenario: Plate with default blur strength shows no label
- **WHEN** a plate has `blur_strength=1.0`
- **THEN** no blur label SHALL be displayed on the plate box
