## MODIFIED Requirements

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
