## Purpose

Run plate detection from the Review page — either on the selected clip, on all clips, or on a single frame — while keeping the UI responsive via a background worker, preserving manual boxes across re-runs, and sharing a cached detector instance.
## Requirements
### Requirement: Detect Plates button on Review page
The Review page SHALL display a "Detect Plates" button that triggers plate detection. The button SHALL be enabled only after analysis is complete (clips are available).

#### Scenario: Button visible after analysis
- **WHEN** the user navigates to the Review page after successful analysis
- **THEN** the "Detect Plates" button SHALL be visible and enabled

#### Scenario: Button disabled during analysis
- **WHEN** analysis is still running or no clips have been loaded
- **THEN** the "Detect Plates" button SHALL be disabled

### Requirement: Scope detection to selected clip or all clips
When a clip is selected in the timeline, clip-wide plate detection SHALL run only on that clip's core source time range `[source_start, source_end)`. Clip-wide detection SHALL NOT extend into the transition tail, because the tail is reserved for user-driven single-frame detection and manual plate placement to keep automatic-scan time predictable. When no clip is selected, clip-wide detection SHALL run on all clips' core ranges. Single-frame detection (the "Detect Frame" button) SHALL be permitted on any frame in the selected clip's effective window (core range ∪ tail).

#### Scenario: Detection with clip selected
- **WHEN** the user selects clip #3 in the timeline and clicks "Detect Plates"
- **THEN** clip-wide detection SHALL run only on the source time range `[source_start, source_end)` of clip #3 and SHALL NOT scan the tail

#### Scenario: Detection with no clip selected
- **WHEN** no clip is selected and the user clicks "Detect Plates"
- **THEN** clip-wide detection SHALL run on all clips' core ranges in sequence; tail frames SHALL NOT be automatically scanned

#### Scenario: Detect Frame at a tail frame
- **WHEN** the selected clip has a transition tail and the playhead is inside that tail
- **THEN** clicking "Detect Frame" SHALL scan that single tail frame and store any detections on the selected clip

### Requirement: Background detection with progress
Plate detection SHALL run in a background thread (PlateDetectionWorker) and display a progress bar on the Review page. The UI SHALL remain responsive during detection.

#### Scenario: Detection progress display
- **WHEN** plate detection is running
- **THEN** a progress bar SHALL show the current progress (e.g., "Detecting plates: clip 2/5, frame 120/300") and a Cancel button SHALL be available

#### Scenario: Detection completes successfully
- **WHEN** plate detection finishes for all requested clips
- **THEN** the progress bar SHALL disappear, detection results SHALL be stored, and the overlay SHALL begin displaying boxes on the current frame

### Requirement: Cancel detection
The user SHALL be able to cancel an in-progress plate detection. Cancellation SHALL preserve any results already collected.

#### Scenario: Cancel mid-detection
- **WHEN** the user clicks Cancel during plate detection
- **THEN** the worker SHALL stop processing, partial results SHALL be retained, and the progress bar SHALL disappear

### Requirement: Re-run detection
The user SHALL be able to re-run plate detection on a clip that already has detection data. Re-running SHALL replace auto-detected boxes but preserve manually added boxes.

#### Scenario: Re-detect on a clip with existing data
- **WHEN** the user runs plate detection on a clip that already has detection results including 2 manual boxes
- **THEN** the auto-detected boxes SHALL be replaced with new detection results, and the 2 manual boxes SHALL be preserved

### Requirement: Detection data persistence
Plate detection results SHALL be stored in memory alongside the clip data during the session. Results are NOT required to persist across application restarts in this initial version.

#### Scenario: Detection data available during review
- **WHEN** plate detection has completed and the user navigates between clips
- **THEN** each clip's detection boxes SHALL be displayed correctly when its frames are shown

#### Scenario: Detection data lost on app restart
- **WHEN** the user closes and reopens the application
- **THEN** plate detection results from the previous session SHALL NOT be available (no persistence requirement)

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
The system SHALL extract the current frame from the video using OpenCV, matching the frame number computed from the player's current time and FPS. The extracted frame SHALL be passed to the detector's tiled detection method. Single-frame detection SHALL be allowed at any source-video frame that belongs to the selected clip's effective window — that is, `[source_start_frame, source_end_frame + tail_frames(clip_index, plan, fps))` as defined by the `plate-clip-transition-tail` capability. When detection at a tail frame returns bounding boxes, the results SHALL be stored under the selected clip's `ClipPlateData.detections[frame]` at the absolute source-video frame key, with no shift or re-assignment to an adjacent clip.

#### Scenario: Frame extraction matches player position
- **WHEN** single-frame detection is triggered
- **THEN** the system reads the frame at the index returned by the shared `VideoPlayer.frame_at` helper (which computes `int(current_time * fps + 1e-9)` via `trailvideocut.utils.frame_math.position_to_frame`) and passes it to `detect_frame_tiled()`

#### Scenario: Frame extraction failure
- **WHEN** the video frame cannot be read (seek failure, corrupted file)
- **THEN** the system displays an error message and does not modify plate data

#### Scenario: Single-frame detection at a tail frame stores under the selected clip
- **WHEN** the selected clip's core ends at source frame 120 with a 6-frame tail, the user is on source frame 123, and Detect Frame finds a plate
- **THEN** the detection SHALL be stored at `clip[selected].detections[123]` with no offset applied, and the overlay SHALL render it as part of the selected clip

### Requirement: Overlay visibility toggle
The Review page SHALL provide a checkbox or toggle button to show/hide the plate overlay. This allows the user to view the clean video without boxes when needed.

#### Scenario: Toggle overlay off
- **WHEN** the user unchecks the "Show Plates" toggle
- **THEN** all plate bounding boxes SHALL be hidden from the video display

#### Scenario: Toggle overlay on
- **WHEN** the user checks the "Show Plates" toggle
- **THEN** plate bounding boxes SHALL be displayed again on the current frame

