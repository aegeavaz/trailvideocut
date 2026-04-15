## Why

Frame-by-frame navigation in the review page is unreliable: pressing the step-forward key sometimes stays on the same frame, or the visual updates but the frame counter does not. This makes manual plate editing frustrating because the user cannot trust that each keypress advances exactly one frame. The root cause is that frame stepping uses a rounded millisecond delta (`round(1000/fps)`) added to the current position, but `int()` truncation when converting back to a frame number can alias to the same frame — especially at non-integer framerates like 29.97 fps where 1 frame ≈ 33.37 ms but the step is only 33 ms.

## What Changes

- **Frame-based stepping with ceil for target ms**: Replace the current "add millisecond delta" approach with "compute target frame number, then seek to `math.ceil(target_frame * 1000.0 / fps)` ms." Using `ceil` (instead of `round`) guarantees the target position lands just past the frame boundary so the round-trip back via `int(pos_s * fps + 1e-9)` reliably returns the intended frame for every common FPS (23.976, 24, 25, 29.97, 30, 50, 59.94, 60).
- **Consistent `int()` frame-number computation**: Unify all frame-from-position calculations to use `int(position_s * fps + 1e-9)` via a shared helper (`VideoPlayer.frame_at` / `trailvideocut.utils.frame_math.position_to_frame`). The tiny epsilon absorbs float round-trip drift (e.g. `4100/1000 * 30` evaluating to `122.9999…`) without crossing any real frame boundary. This matches OpenCV/FFmpeg source-frame indexing so plate keys stored by the detector line up exactly with the blur/export pipeline's iteration variable.
- **Preview-mode frame stepping**: Apply the same ceil-based stepping in preview mode transport handling.

## Capabilities

### New Capabilities

- `frame-precise-navigation`: Ensure frame-by-frame stepping always advances/retreats exactly one frame and all frame number displays stay synchronized with the actual seek position.

### Modified Capabilities


## Impact

- `src/trailvideocut/utils/frame_math.py` — new module with `position_to_frame` and `frame_to_position_ms` helpers.
- `src/trailvideocut/ui/video_player.py` — `frame_at`, `frame_to_ms`, `_step_forward`, `_step_back`, `_update_time_label`, `update_time_label_external`.
- `src/trailvideocut/ui/review_page.py` — `_handle_transport` (preview step_forward/step_back, frame-based), `_update_plate_overlay_frame`, `_update_frame_buttons`, `_on_clear_frame_plates`, `_sync_overlay_to_current_clip`, `_run_single_frame_detection`.
