## 1. Frame-step math fix

- [x] 1.1 Add `VideoPlayer._frame_center_ms(frame: int) -> int` in `src/trailvideocut/ui/video_player.py` that returns `int((frame + 0.5) * 1000.0 / self._fps)`, clamped to 0 for `frame <= 0`.
- [x] 1.2 Update `VideoPlayer._step_forward` to use `_frame_center_ms(current_frame + 1)` as the seek target, replacing the boundary-based `frame_to_ms(current_frame + 1)`.
- [x] 1.3 Update `VideoPlayer._step_back` to use `_frame_center_ms(current_frame - 1)` as the seek target, replacing the boundary-based `frame_to_ms(current_frame - 1)`.
- [x] 1.4 Verify that `frame_to_position_ms` and `position_to_frame` in `src/trailvideocut/utils/frame_math.py` are NOT changed — they remain correct for detection storage keys, slider math, and export iteration.

## 2. Backend pinning

- [x] 2.1 Add `os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")` at the top of `src/trailvideocut/ui/app.py`, before any `from PySide6.QtMultimedia ...` or QApplication construction.
- [x] 2.2 Add a short comment explaining why the env var is set (frame-accurate stepping relies on FFmpeg-backend behavior; WMF regresses it).

## 3. Specification alignment

- [x] 3.1 Update the `frame-precise-navigation` spec's "Frame-based step forward" and "Frame-based step backward" requirements and scenarios to reflect the centre-of-window formula.
- [x] 3.2 Update the preview-mode consistency scenario to reference the same centre formula.
- [x] 3.3 Keep the "Consistent frame number computation" requirement unchanged — `position_to_frame` is not modified.

## 4. Verification

- [x] 4.1 Instrumented diagnostic reproduction confirmed the fix: every `[PlateDiag sink] sink_frame=N` now matches `[PlateDiag overlay] set_current_frame=N` after → and ← presses in both directions, across many frames. User confirmed "Looks good now!".
- [x] 4.2 All diagnostic instrumentation removed from the production code paths (detector, review_page, plate_overlay, video_player) and confirmed via `git diff` that only the step-math helper and the env var remain.
- [x] 4.3 Imports verified clean after the revert (`python -c "from trailvideocut.ui.app import launch; ..."`).

## 5. Follow-up (separate change if still reproducible)

- [ ] 5.1 Re-verify the originally-reported export-side displacement ("if I export to video, all the automatic plates are displaced") with a fresh export after this fix. If the preview that the user was using to judge plate positions was the only thing wrong, the exported video may already be correct.
- [ ] 5.2 If export displacement still reproduces, open a *separate* OpenSpec change — do not bundle it here. The export pipeline uses MoviePy + content-based calibration, not QMediaPlayer, so the mechanism must differ.
