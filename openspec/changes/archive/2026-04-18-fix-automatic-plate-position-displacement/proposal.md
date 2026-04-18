## Why

When the user pressed the arrow keys after automatic plate detection, the plate overlay box moved to the next frame's coordinates but the video pixels stayed on the previous frame. After a forward-then-back round-trip, the originally-correct frame also looked misaligned. The export pipeline inherited the same misalignment, so automatic plate blurs were offset from the plates they were meant to cover.

Diagnostic instrumentation of `QVideoSink.videoFrameChanged` against `QMediaPlayer.position()` isolated the mechanism. The step math computes `frame_to_ms(N) = ceil(N * 1000 / fps)` — the *leading edge* of frame N under the ideal `t = N/fps` model. Real H.264/HEVC containers carry a small constant offset between that ideal and the actual presentation timestamp on the decoded frame. On the user's 23.976-fps source, frame 5993's sink-reported `startTime` was 249.9723 s, whereas the ideal math places it at 249.9643 s — an 8 ms lag. When `_step_forward` targets `ceil(5994 * 1000 / fps) = 250006 ms`, the backend correctly observes that 250.006 s still falls inside frame 5993's real window `[249.9723 s, 250.0141 s)` and refuses to re-decode. `position()` advances, `position_to_frame` reports 5994, the overlay updates to frame 5994's box — but the video surface is still frame 5993. Detection, storage, overlay rendering, and export pipeline were all operating on correct data; only the step-target ms was wrong.

## What Changes

- **Modify the frame-step seek target** to land inside the *centre* of the target frame's ideal window instead of its leading edge. `_frame_center_ms(N) = int((N + 0.5) * 1000.0 / fps)` gives ~half a frame of margin in each direction, comfortably absorbing any realistic container presentation offset (observed offsets are under 10 ms; the margin is ~21 ms at 23.976 fps).
- **Defensively pin Qt's multimedia backend to FFmpeg** via `QT_MEDIA_BACKEND=ffmpeg` at application startup so frame-accurate stepping does not silently regress if a future build ships without the FFmpeg plugin (Qt's Media Foundation backend on Windows does not re-decode on paused `setPosition()` at all).
- **No changes to detection storage, overlay rendering, export pipeline, sidecar format, or any data layout.** Those were investigated and ruled out as the source of the displacement.

## Capabilities

### Modified Capabilities
- `frame-precise-navigation`: Step-forward and step-backward SHALL target a position inside the target frame's actual presentation window, not the ideal leading edge. The scenarios that pin exact ms values for specific frame indices change to the center-of-window formula.

## Impact

- **Code**:
  - `src/trailvideocut/ui/video_player.py::_step_forward`, `::_step_back`, new private `::_frame_center_ms` — compute target ms as `int((frame + 0.5) * 1000.0 / fps)`.
  - `src/trailvideocut/ui/app.py` — `os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")` before any Qt multimedia import.
- **APIs**: None external. `frame_to_position_ms` in `utils/frame_math.py` is unchanged; it remains correct for boundary-based uses (slider math, detection storage keys).
- **Persistence**: None. Existing sidecar plate data remains valid; no migration.
- **Dependencies**: None added.
- **Tests**: Existing `frame-precise-navigation` scenarios that assert specific ms targets (e.g. "34 ms for frame 1 at 29.97 fps") change to the center formula (`int(1.5 * 1000 / 29.97) = 50 ms`).
