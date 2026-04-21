## MODIFIED Requirements

### Requirement: Clear all plates in current frame
The system SHALL provide a "Clear Frame Plates" button that deletes all plate boxes (both auto-detected and manual) for the currently displayed frame. The operation SHALL NOT require confirmation (low-impact, recoverable). After clearing, plate data for the frame SHALL be removed and persisted. For the purposes of the button's enabled state and the key it uses to delete an entry, the "selected clip" SHALL include its transition tail as defined by the `plate-clip-transition-tail` capability — i.e. a current frame that lies in `[source_end_frame, source_end_frame + tail_frames)` of the selected clip is treated as belonging to that clip. The frame key deleted from `ClipPlateData.detections` SHALL be the absolute source-video frame number.

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
- **WHEN** no clip is selected, or the selected clip has no plate data, or the current frame has no plates in the selected clip's `ClipPlateData.detections` (regardless of whether the playhead is in the core range or the transition tail)
- **THEN** the "Clear Frame Plates" button SHALL be disabled

#### Scenario: Clear plate at a tail frame
- **WHEN** the selected clip's core ends at frame 120 with a 6-frame tail, a plate is stored at `detections[123]` of that clip, and the playhead is at frame 123
- **THEN** "Clear Frame Plates" SHALL be enabled, and clicking it SHALL remove `detections[123]` from that clip's data and persist the update

### Requirement: Clear all plates in selected clip
The system SHALL provide a "Clear Clip Plates" button that deletes all plate boxes (both auto-detected and manual) for the currently selected clip. The operation SHALL require user confirmation via a dialog before proceeding. After clearing, plate data for the clip SHALL be removed from memory and persisted to disk. The operation SHALL also remove any plates stored at source-frame keys that fall inside the clip's transition tail (as defined by `plate-clip-transition-tail`) — tail plates are part of the clip for management purposes.

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

#### Scenario: Clip with only tail-region plates
- **WHEN** the selected clip has plates only at source-frame indices inside its transition tail and none in the core range
- **THEN** "Clear Clip Plates" SHALL still be enabled and, on confirmation, SHALL remove those tail-region plates together with any core-range plates
