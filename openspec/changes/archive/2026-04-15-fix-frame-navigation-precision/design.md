## Context

The application uses `QMediaPlayer` for video playback, which operates in millisecond resolution. Frame-by-frame stepping originally worked by computing a millisecond delta (`round(1000 / fps)`) and adding it to the current position; the frame counter label then computed the frame number by `int(position_ms / 1000.0 * fps)`.

For non-integer framerates (e.g. 29.97 fps), the rounded delta (33 ms) is shorter than one actual frame duration (33.37 ms). Stepping forward from the start of a frame lands at a position that still truncates to the same frame number — the visual may update (the decoder shows the next keyframe) but the frame counter stays the same, or vice versa.

Frame numbers were also computed independently in at least four places (`_update_time_label`, `update_time_label_external`, `_update_plate_overlay_frame`, `_update_frame_buttons` / `_on_clear_frame_plates` / `_sync_overlay_to_current_clip`) — all using `int()` truncation, inconsistent with the step logic's `round()` delta.

## Goals / Non-Goals

**Goals:**
- Each press of step-forward/step-back SHALL advance/retreat exactly one frame.
- The frame counter label, the plate overlay frame number, plate-storage keys, and every internal frame calculation SHALL agree on the current frame number for any given position.
- The fix SHALL work correctly for all common video framerates (23.976, 24, 25, 29.97, 30, 50, 59.94, 60).
- The frame-number semantic SHALL align with OpenCV/FFmpeg source-frame indexing so plate detections (stored by `cap.set + cap.read` iteration) line up with the blur/export pipeline's frame walk.

**Non-Goals:**
- Variable frame rate (VFR) video support — OpenCV already reports a single FPS value.
- Sub-frame precision or timecode display (SMPTE, drop-frame).
- Changing the `QMediaPlayer` backend or its millisecond resolution constraint.

## Decisions

### Decision 1: Frame-based stepping with `math.ceil` for the target ms

**Choice:** Compute target frame = `current_frame ± 1`, then seek to `math.ceil(target_frame * 1000.0 / fps)` ms.

**Rationale:** The original approach of adding a fixed ms delta can land in the previous frame for non-integer FPS. We considered `round(target_frame * 1000.0 / fps)`, which also works for the display label, but `round` can land *exactly at* or *just before* the frame boundary, so when we convert back via `int(pos_s * fps)` the result drops to `target_frame - 1` once float drift enters the equation. `ceil` guarantees the seek position is strictly past the boundary — every common FPS we tested (23.976 → 60) round-trips correctly, and there is no cumulative drift across hundreds of consecutive steps (verified by `tests/test_frame_navigation.py::TestStepForwardBack`).

**Alternatives considered:**
- `round(target_frame * 1000.0 / fps)` — fails the `int()` round-trip at integer FPS where the product is exactly on an integer ms boundary; float representation error (e.g. `4100/1000 * 30 = 122.9999…`) then truncates to the previous frame.
- Fractional-ms accumulator — extra state, doesn't fix the fundamental ms-resolution constraint.

### Decision 2: Use `int()` with a float-precision epsilon for position → frame

**Choice:** Replace every ad-hoc `int(position * fps)` / `round(position * fps)` with a single helper `position_to_frame(pos_s, fps) = int(pos_s * fps + 1e-9)`.

**Rationale:** OpenCV and FFmpeg index source frames via `int(pos_s * fps)` — plates stored by `_detect_clip_opencv` are keyed by the iteration index, which is exactly this integer. Using the same semantic everywhere means no translation layer is needed between the UI (QMediaPlayer position), the plate store, and the export pipeline. The `1e-9` epsilon absorbs float-precision drift on ms ↔ s ↔ frame round-trips; it's orders of magnitude smaller than any real frame duration (at 1000 fps that would be 1 ms, still 1,000,000× larger than the epsilon), so it never crosses a real frame boundary.

### Decision 3: Centralize frame number computation

**Choice:** Expose `position_to_frame` / `frame_to_position_ms` in `trailvideocut.utils.frame_math`, and call them from `VideoPlayer.frame_at` / `frame_to_ms`. Every call site uses the `VideoPlayer` instance methods.

**Rationale:** A single source of truth eliminates the class of bugs where different call sites disagree on "what frame are we on." The helpers live in a Qt-free module so tests can exercise the math directly without instantiating `QApplication`.

## Risks / Trade-offs

- **[Risk]** The epsilon could theoretically snap a position that is genuinely between frames to the next frame. → **Mitigation**: `1e-9` is far below any plausible frame period; a position this close to a boundary is indistinguishable from the boundary for UI/plate purposes.
- **[Risk]** `math.ceil` target_ms may overshoot by 1 ms in rare cases where the exact boundary is an integer. → **Mitigation**: 1 ms is always ≪ 1 frame (smallest case: 60 fps ≈ 16.7 ms), so the overshoot still sits cleanly inside frame N.
- **[Trade-off]** Two public API methods on `VideoPlayer` instead of a private helper, but the win in consistency and testability outweighs the surface-area cost.
