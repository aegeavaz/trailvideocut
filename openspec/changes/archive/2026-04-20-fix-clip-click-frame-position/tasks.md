## 1. Regression tests (TDD)

- [x] 1.1 Locate the existing `VideoPlayer` / frame-math test module (e.g. `tests/ui/test_video_player.py`) and confirm the mocking pattern used by the 2026-04-18 fix so the new tests stay consistent.
- [x] 1.2 Add a failing test: `seek_to(1.0)` at 23.976 fps calls the underlying `_seek` with 980 ms (centre of source frame 23), not 1000 ms.
- [x] 1.3 Add a failing test: `seek_to(0.034)` at 29.97 fps calls `_seek` with 50 ms (centre of frame 1), not 34 ms.
- [x] 1.4 Add a failing test: `seek_to(0.0)` calls `_seek(0)` (clamped centre of frame 0).
- [x] 1.5 Add a failing test: `seek_to(seconds)` whose raw centre-of-frame target exceeds `_duration_ms` clamps to `_duration_ms`.
- [x] 1.6 Add a failing test: `seek_to` resolves the frame via `utils.frame_math.position_to_frame` (e.g. `seek_to(4.1)` at 30 fps → frame 123, `_seek(4116 or 4117)` rather than frame 122) to pin the 1e-9 epsilon behaviour.
- [x] 1.7 Run the test suite to confirm 1.2–1.6 fail against the current `int(seconds * 1000)` implementation.

## 2. Implementation

- [x] 2.1 In `src/trailvideocut/ui/video_player.py`, import `position_to_frame` from `trailvideocut.utils.frame_math` (if not already imported).
- [x] 2.2 Replace the body of `VideoPlayer.seek_to(seconds)` with the centre-of-window path: resolve `frame = position_to_frame(max(seconds, 0.0), self._fps)`, compute `target_ms = self._frame_center_ms(frame)`, clamp to `min(target_ms, self._duration_ms)`, then call `self._seek(...)`.
- [x] 2.3 Re-run the failing tests from section 1; confirm they pass.

## 3. Manual verification

- [ ] 3.1 Launch the app on a 23.976 fps source, open a project with at least 10 clips, and click through clips in the Review-page clip list. For each click, confirm the F-label, plate overlay, and displayed pixels all report the same frame (and match `clip.source_start`'s resolved frame).
- [ ] 3.2 Repeat on a 29.97 fps source and a 30 fps source to confirm non-integer and integer FPS both land correctly.
- [ ] 3.3 In Setup page, jump between marks via the mark list and confirm the displayed frame matches the mark's frame.
- [ ] 3.4 In Review page preview mode, let a re-seek trigger (e.g. seek mid-clip through the scrubber) and confirm the corrected position lands on the expected frame.

## 4. Regression sweep

- [x] 4.1 Run the full unit test suite (`pytest`) and confirm no other test asserts on the old `int(seconds * 1000)` ms value for `seek_to`. (531 passed, 11 skipped)
- [x] 4.2 Verify `openspec validate fix-clip-click-frame-position` reports no schema errors.
- [x] 4.3 Update any stale test that asserted on the old ms value (if found in 4.1), pointing it at the new centre-of-window ms. (no stale tests — only the new seek_to suite asserts on ms values)
