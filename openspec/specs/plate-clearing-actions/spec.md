## ADDED Requirements

### Requirement: Clear all plates in selected clip
The system SHALL provide a "Clear Clip Plates" button that deletes all plate boxes (both auto-detected and manual) for the currently selected clip. The operation SHALL require user confirmation via a dialog before proceeding. After clearing, plate data for the clip SHALL be removed from memory and persisted to disk.

#### Scenario: User clears clip plates with confirmation
- **WHEN** the user clicks "Clear Clip Plates" and confirms in the dialog
- **THEN** the system removes all plate data for the selected clip, persists the updated data, refreshes the overlay to show no boxes, and updates the plate list widget

#### Scenario: User cancels clip clearing
- **WHEN** the user clicks "Clear Clip Plates" and cancels in the confirmation dialog
- **THEN** no plate data is modified

#### Scenario: Clear clip plates when it's the only clip with data
- **WHEN** the user clears clip plates and no other clips have plate data
- **THEN** the system removes the clip's plate data, deletes the sidecar file if no plate data remains, and disables plate UI controls (same behavior as "Clear Saved Plates")

#### Scenario: Button disabled state
- **WHEN** no clip is selected, or the selected clip has no plate data
- **THEN** the "Clear Clip Plates" button SHALL be disabled

### Requirement: Clear all plates in current frame
The system SHALL provide a "Clear Frame Plates" button that deletes all plate boxes (both auto-detected and manual) for the currently displayed frame. The operation SHALL NOT require confirmation (low-impact, recoverable). After clearing, plate data for the frame SHALL be removed and persisted.

#### Scenario: User clears frame plates
- **WHEN** the user clicks "Clear Frame Plates" with plates present on the current frame
- **THEN** the system removes the frame entry from the clip's detections dict, persists the updated data, refreshes the overlay to show no boxes for this frame, and updates the plate list widget

#### Scenario: Clear frame plates when no plates on current frame
- **WHEN** the user clicks "Clear Frame Plates" and the current frame has no plates
- **THEN** the button click has no effect (no-op)

#### Scenario: Keyboard shortcut clears frame when no plate selected
- **WHEN** the user presses Delete or Backspace with no plate box selected
- **THEN** the system clears all plates on the current frame (identical to clicking "Clear Frame Plates")

#### Scenario: Keyboard shortcut deletes single plate when one is selected
- **WHEN** the user presses Delete or Backspace with a plate box selected
- **THEN** only the selected plate is deleted (existing single-delete behavior)

#### Scenario: Button disabled state
- **WHEN** no clip is selected, or the selected clip has no plate data, or the current frame has no plates
- **THEN** the "Clear Frame Plates" button SHALL be disabled
