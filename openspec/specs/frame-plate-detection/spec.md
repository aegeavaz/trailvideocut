## ADDED Requirements

### Requirement: Detect plates in current frame
The system SHALL provide a "Detect Frame" button that runs plate detection on the single frame currently displayed in the video player. Detection SHALL use the same confidence threshold, phone exclusion, aspect ratio, and geometry filter settings as clip-level detection. The button SHALL be enabled only when a clip with plate data is selected and the video is loaded.

#### Scenario: User detects plates on current frame
- **WHEN** the user clicks "Detect Frame" with a valid clip selected and video loaded
- **THEN** the system runs tiled plate detection on the current frame using current UI settings, replaces auto-detected boxes for that frame while preserving manual boxes, persists the updated plate data, and refreshes the overlay

#### Scenario: Detect frame with existing manual boxes
- **WHEN** the user clicks "Detect Frame" on a frame that has manual plate boxes
- **THEN** the auto-detected boxes for that frame are replaced with new detections, all manual boxes on that frame are preserved, and the merged result is saved

#### Scenario: Detect frame with no prior plate data for clip
- **WHEN** the user clicks "Detect Frame" and the selected clip has no existing plate data
- **THEN** the system creates a new ClipPlateData for the clip, stores the single-frame detection result, and enables plate UI controls

#### Scenario: Detect frame when model is not downloaded
- **WHEN** the user clicks "Detect Frame" and the detection model is not cached
- **THEN** the system initiates the model download flow (same as clip detection) and runs single-frame detection after download completes

#### Scenario: Button disabled state
- **WHEN** no clip is selected, or no video is loaded, or clip-level detection is running
- **THEN** the "Detect Frame" button SHALL be disabled
