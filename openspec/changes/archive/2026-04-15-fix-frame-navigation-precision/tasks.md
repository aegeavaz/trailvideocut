## 1. Centralize frame computation in VideoPlayer

- [x] 1.1 Add `frame_at(position_s: float) -> int` method to `VideoPlayer` that returns `int(position_s * self._fps + 1e-9)` (via `trailvideocut.utils.frame_math.position_to_frame`)
- [x] 1.2 Add `frame_to_ms(frame: int) -> int` helper method that returns `math.ceil(frame * 1000.0 / self._fps)` (via `frame_math.frame_to_position_ms`)

## 2. Fix frame stepping in VideoPlayer

- [x] 2.1 Rewrite `_step_forward` to compute current frame via `frame_at`, then seek to `frame_to_ms(current_frame + 1)` clamped to duration
- [x] 2.2 Rewrite `_step_back` to compute current frame via `frame_at`, then seek to `frame_to_ms(current_frame - 1)` clamped to 0

## 3. Unify frame number display

- [x] 3.1 Update `_update_time_label` to use `frame_at(self.current_time)` instead of `int(position_ms / 1000.0 * fps)`
- [x] 3.2 Update `update_time_label_external` to use `frame_at(current_s)` instead of `int(current_s * fps)`

## 4. Fix frame computation in ReviewPage

- [x] 4.1 Update `_update_plate_overlay_frame` to use `self._player.frame_at(position)` instead of `int(position * fps)`
- [x] 4.2 Update `_sync_overlay_to_current_clip` to use `self._player.frame_at(...)` instead of `int(current_time * fps)`
- [x] 4.3 Update `_update_frame_buttons` to use `self._player.frame_at(...)` instead of `int(current_time * fps)`
- [x] 4.4 Update `_on_clear_frame_plates` to use `self._player.frame_at(...)` instead of `int(current_time * fps)`

## 5. Fix preview-mode stepping

- [x] 5.1 Update `_handle_transport` for `step_forward`/`step_back` to use frame-based stepping via `frame_at` and `frame_to_ms` instead of `int(1000.0 / fps)` delta

## 6. Testing

- [x] 6.1 Write unit tests for `frame_at` with edge cases: 29.97 fps boundary positions, 0ms, exact frame boundaries, end-of-video
- [x] 6.2 Write unit tests for `frame_to_ms` verifying round-trip consistency: `frame_at(frame_to_ms(n) / 1000.0) == n` for all frames
- [x] 6.3 Write unit tests for step-forward/step-back verifying frame number increments by exactly 1 at various FPS values
