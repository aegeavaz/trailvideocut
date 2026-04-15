## ADDED Requirements

### Requirement: Frame-based step forward
The system SHALL advance exactly one frame when the user triggers step-forward (right arrow key or ▷ button). The seek position MUST be computed as `math.ceil((current_frame + 1) * 1000.0 / fps)` milliseconds so that the resulting position, when converted back via `int(pos_ms / 1000 * fps)`, reliably maps to the target frame even for non-integer FPS.

#### Scenario: Step forward at 29.97 fps from frame 0
- **WHEN** the video is at position 0 ms (frame 0) at 29.97 fps and the user presses the right arrow key
- **THEN** the player seeks to position 34 ms (`ceil(1000/29.97) = 34`) and the frame counter displays "F: 1"

#### Scenario: Step forward at 29.97 fps from frame 1
- **WHEN** the video is at position 34 ms (frame 1) at 29.97 fps and the user presses the right arrow key
- **THEN** the player seeks to position 67 ms (`ceil(2·1000/29.97) = 67`) and the frame counter displays "F: 2"

#### Scenario: Step forward at video end
- **WHEN** the video is at the last frame and the user presses the right arrow key
- **THEN** the position SHALL NOT exceed the video duration

### Requirement: Frame-based step backward
The system SHALL retreat exactly one frame when the user triggers step-backward (left arrow key or ◁ button). The seek position MUST be computed as `math.ceil((current_frame - 1) * 1000.0 / fps)` milliseconds, clamped to 0 for frame 0.

#### Scenario: Step backward at 29.97 fps from frame 2
- **WHEN** the video is at frame 2 at 29.97 fps and the user presses the left arrow key
- **THEN** the player seeks to the position of frame 1 (34 ms) and the frame counter displays "F: 1"

#### Scenario: Step backward at video start
- **WHEN** the video is at frame 0 and the user presses the left arrow key
- **THEN** the position SHALL NOT go below 0

### Requirement: Consistent frame number computation
All code paths that convert a time position to a frame number SHALL use a single centralized method (`VideoPlayer.frame_at`, backed by `trailvideocut.utils.frame_math.position_to_frame`) that computes `int(position_seconds * fps + 1e-9)`. This matches OpenCV/FFmpeg source-frame indexing; the 1e-9 epsilon absorbs float-precision drift on millisecond round-trips without crossing any real frame boundary. The frame counter label, the plate overlay frame tracking, per-frame plate storage keys, and frame-related button state checks SHALL all share this helper.

#### Scenario: Frame counter matches plate overlay frame
- **WHEN** the video is at any position
- **THEN** the frame number shown in the "F:" label SHALL equal the frame number used by the plate overlay for box lookup

#### Scenario: Position inside frame 0 at 29.97 fps
- **WHEN** the video is at position 0.033 s at 29.97 fps (0.033 × 29.97 ≈ 0.989)
- **THEN** the frame number SHALL be `int(0.989 + 1e-9)` = 0, since frame 1's PTS is at 1/29.97 ≈ 0.0334 s

#### Scenario: Position inside frame 1 at 29.97 fps
- **WHEN** the video is at position 0.034 s at 29.97 fps (0.034 × 29.97 ≈ 1.019)
- **THEN** the frame number SHALL be `int(1.019 + 1e-9)` = 1

#### Scenario: Round-trip consistency on integer FPS
- **WHEN** `frame_to_position_ms(123, 30.0)` returns 4100 ms and is round-tripped back via `position_to_frame(4.1, 30.0)`
- **THEN** the result SHALL be 123 (the epsilon prevents the float product `4.1 × 30 = 122.9999…` from truncating to 122)

### Requirement: Preview-mode frame stepping consistency
When in preview mode, step-forward and step-back transport actions SHALL use the same frame-based stepping logic as normal mode, computing target frame from current position rather than adding a millisecond delta.

#### Scenario: Preview step forward
- **WHEN** in preview mode and the user steps forward
- **THEN** the music position advances to `math.ceil((current_video_frame + 1) * 1000.0 / fps)` ms, i.e. exactly one video-frame duration computed from the target frame number
