# frame-precise-navigation Specification

## Purpose
Guarantee that frame-by-frame navigation in the video player advances or retreats exactly one frame per keypress, and that every surface showing a "current frame" (time label, plate overlay, plate storage keys, per-frame button enables, export pipeline iteration) agrees on the same integer frame number for any given playback position. The canonical formulas live in `trailvideocut.utils.frame_math`:

- `position_to_frame(pos_s, fps) = int(pos_s * fps + 1e-9)` — matches OpenCV/FFmpeg source-frame indexing; the ε absorbs float-precision drift on ms↔s↔frame round-trips.
- `frame_to_position_ms(frame, fps) = math.ceil(frame * 1000.0 / fps)` — the target ms lands just past the frame boundary so the round-trip back via `int()` reliably returns the intended frame.
## Requirements
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
- **THEN** the music position advances by exactly one video-frame duration computed from the target frame number, using the same centre-of-window formula the main player uses (`int((target_frame + 0.5) * 1000.0 / fps)`)

### Requirement: Seconds-valued seek lands centre-of-frame
The system SHALL resolve any seconds-valued seek request issued through `VideoPlayer.seek_to(seconds)` to the source-frame index the decoder displays at that time (`position_to_frame(seconds, fps)`) and drive the underlying `_seek` with `_frame_center_ms(frame)` — i.e. `int((frame + 0.5) * 1000.0 / fps)` — clamped to `[0, duration_ms]`. Targeting the centre of the target frame's ideal window (instead of the naive `int(seconds * 1000)` leading-edge conversion) gives approximately half a frame of slack in each direction, absorbing the per-frame presentation-timestamp offset that H.264/HEVC containers commonly carry relative to the `t = N/fps` model. This makes every programmatic seek — clip-list clicks, preview re-seeks, mark jumps — land on the same frame the playhead reports and the overlay renders, regardless of the container's PTS offset.

#### Scenario: Clip-list click at 23.976 fps lands on clip's start frame
- **WHEN** the user clicks a clip in the Review-page clip list whose `clip.source_start` is `1.0` s on a 23.976 fps source and `seek_to(1.0)` is invoked
- **THEN** the resulting `_seek` target is `int((position_to_frame(1.0, 23.976) + 0.5) * 1000.0 / 23.976)` = `int((23 + 0.5) * 1000.0 / 23.976)` = 980 ms (the centre of source frame 23) and `QVideoSink`'s next emitted frame has a `startTime` corresponding to source frame 23

#### Scenario: Clip-list click at 29.97 fps on a non-integer frame time
- **WHEN** `seek_to(0.034)` is invoked on a 29.97 fps source (position_to_frame = 1)
- **THEN** the resulting `_seek` target is `int(1.5 * 1000.0 / 29.97)` = 50 ms (the centre of frame 1) rather than `34` ms (which can fall inside frame 0's actual presentation window) and the decoder lands on source frame 1

#### Scenario: Clip-list click at start of video
- **WHEN** `seek_to(0.0)` is invoked
- **THEN** the resulting `_seek` target is 0 ms (frame 0's clamped centre) and the decoder lands on source frame 0

#### Scenario: Clip-list click past the end of the video
- **WHEN** `seek_to(seconds)` is invoked with a value whose centre-of-frame target would exceed the loaded duration
- **THEN** the `_seek` target SHALL be clamped to `duration_ms` and the decoder SHALL NOT seek past the last frame

#### Scenario: Preview mid-clip re-seek uses the same centre-of-window rule
- **WHEN** the Review-page preview detects a drift and calls `seek_to(expected_source_pos)` with a fractional seconds value
- **THEN** the resolved `_seek` target is the centre of `position_to_frame(expected_source_pos, fps)` (same formula as the clip-list click path) and the displayed frame matches the expected source frame

