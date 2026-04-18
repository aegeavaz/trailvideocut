## MODIFIED Requirements

### Requirement: Frame-based step forward
The system SHALL advance exactly one frame when the user triggers step-forward (right arrow key or ▷ button). The seek position MUST be computed as `int((current_frame + 1 + 0.5) * 1000.0 / fps)` milliseconds — the centre of the target frame's ideal window. Targeting the centre (rather than the ideal leading edge) gives approximately half a frame of slack in each direction, absorbing the presentation-timestamp offset that H.264/HEVC containers commonly exhibit relative to the `t = N/fps` model. When the step math targets the leading edge, the resulting position can fall inside the *previous* frame's actual presentation window, leaving the video surface on the wrong frame while `position()` and the overlay advance; the centre formula prevents that desynchronisation for any realistic offset.

#### Scenario: Step forward at 29.97 fps from frame 0
- **WHEN** the video is at position 0 ms (frame 0) at 29.97 fps and the user presses the right arrow key
- **THEN** the player seeks to position 50 ms (`int(1.5 * 1000 / 29.97) = 50`) and the frame counter displays "F: 1"

#### Scenario: Step forward at 29.97 fps from frame 1
- **WHEN** the video is at position ~50 ms (frame 1) at 29.97 fps and the user presses the right arrow key
- **THEN** the player seeks to position 83 ms (`int(2.5 * 1000 / 29.97) = 83`) and the frame counter displays "F: 2"

#### Scenario: Step forward at video end
- **WHEN** the video is at the last frame and the user presses the right arrow key
- **THEN** the position SHALL NOT exceed the video duration

#### Scenario: Step forward lands the video surface on the target frame
- **WHEN** the video is paused on source frame N and the user presses the right arrow key once
- **THEN** `QVideoSink`'s subsequently emitted frame SHALL have a `startTime` corresponding to source frame N+1 (i.e. the displayed pixels advance together with the position and overlay), provided the container's per-frame presentation-timestamp offset from the ideal `t = N/fps` model is smaller in magnitude than `500 / fps` milliseconds

### Requirement: Frame-based step backward
The system SHALL retreat exactly one frame when the user triggers step-backward (left arrow key or ◁ button). The seek position MUST be computed as `int((current_frame - 1 + 0.5) * 1000.0 / fps)` milliseconds — the centre of the target frame's ideal window — clamped to 0 for frame 0. The reasoning matches step-forward: centre-of-window targeting keeps the seek inside the target frame's actual presentation window regardless of the container's constant offset, so the video surface decodes the intended frame rather than one before it.

#### Scenario: Step backward at 29.97 fps from frame 2
- **WHEN** the video is at frame 2 at 29.97 fps and the user presses the left arrow key
- **THEN** the player seeks to position 50 ms (`int(1.5 * 1000 / 29.97) = 50`, the centre of frame 1) and the frame counter displays "F: 1"

#### Scenario: Step backward at video start
- **WHEN** the video is at frame 0 and the user presses the left arrow key
- **THEN** the position SHALL NOT go below 0

#### Scenario: Step backward lands the video surface on the target frame
- **WHEN** the video is paused on source frame N (N > 0) and the user presses the left arrow key once
- **THEN** `QVideoSink`'s subsequently emitted frame SHALL have a `startTime` corresponding to source frame N-1 (overlay, position, and pixels agree), provided the container's per-frame presentation-timestamp offset from the ideal `t = N/fps` model is smaller in magnitude than `500 / fps` milliseconds

### Requirement: Preview-mode frame stepping consistency
When in preview mode, step-forward and step-back transport actions SHALL use the same frame-based stepping logic as normal mode, computing target frame from current position rather than adding a millisecond delta.

#### Scenario: Preview step forward
- **WHEN** in preview mode and the user steps forward
- **THEN** the music position advances by exactly one video-frame duration computed from the target frame number, using the same centre-of-window formula the main player uses (`int((target_frame + 0.5) * 1000.0 / fps)`)
