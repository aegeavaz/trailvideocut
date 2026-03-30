## ADDED Requirements

### Requirement: Single-frame detection entry point
The plate detection workflow SHALL support a single-frame detection mode that reuses the existing detector infrastructure. The detector instance SHALL be lazily cached to avoid repeated model loading. Current UI filter settings (confidence, phone exclusion, aspect ratio, geometry) SHALL be applied to single-frame detection.

#### Scenario: First single-frame detection initializes detector
- **WHEN** the user triggers single-frame detection for the first time
- **THEN** the system creates and caches a PlateDetector instance using the current model path and settings

#### Scenario: Subsequent detections reuse cached detector
- **WHEN** the user triggers single-frame detection again with unchanged settings
- **THEN** the system reuses the cached PlateDetector without reinitializing

#### Scenario: Settings changed between detections
- **WHEN** the user changes detection settings (confidence, filters) and triggers single-frame detection
- **THEN** the system creates a new PlateDetector with updated settings, replacing the cached instance

### Requirement: Frame extraction for single-frame detection
The system SHALL extract the current frame from the video using OpenCV, matching the frame number computed from the player's current time and FPS. The extracted frame SHALL be passed to the detector's tiled detection method.

#### Scenario: Frame extraction matches player position
- **WHEN** single-frame detection is triggered
- **THEN** the system reads the frame at position `round(current_time * fps)` from the video file and passes it to `detect_frame_tiled()`

#### Scenario: Frame extraction failure
- **WHEN** the video frame cannot be read (seek failure, corrupted file)
- **THEN** the system displays an error message and does not modify plate data
