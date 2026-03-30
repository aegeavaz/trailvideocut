## ADDED Requirements

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
