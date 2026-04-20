## ADDED Requirements

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
