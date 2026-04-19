## 1. Failing integration test (TDD red)

- [x] 1.1 Added fixture helper `_make_frame_number_clip` in `tests/test_export_plate_frame_alignment.py` (flat test layout — no `tests/integration/` in this project). Writes a 60-frame `mp4v` clip with a shared fine-grained checkerboard body + a per-frame colour-coded top strip. No `drawtext` dependency.
- [x] 1.2 Added `tests/test_export_plate_frame_alignment.py::test_process_segment_uses_exact_source_frame_key`. Populates detections at every frame 1..58 with one of three non-overlapping box regions (LEFT / CENTER / RIGHT) cycled by `n % 3`, runs `PlateBlurProcessor.process_segment` directly (deterministic; no full assembler round-trip needed), decodes the raw I420 output, and asserts the blurred region at probe frames 10/15/20/30/40/50 matches `n % 3` (not `(n±1) % 3`).
- [x] 1.3 Ran against current code: test FAILS at frame 10 with `std=124.7 >= threshold=74.9` — CENTER region (expected blurred per `n%3=1`) is unblurred, consistent with the `+1` offset having looked up `detections[11]` (RIGHT) instead of `detections[10]` (CENTER).

## 2. Remove the MP4 frame offset (TDD green)

- [x] 2.1 `PlateBlurProcessor.process_segment` now uses `lookup_frame = abs_frame` (blur.py:517-521). No helper introduced — the integration test from §1 is the regression guard.
- [x] 2.2 Deleted the 7-line comment above the old `+1` that justified the obsolete mid-GOP rationale.
- [x] 2.3 Rewrote `process_segment`'s docstring to describe direct-key lookup with ±2 nearest-neighbour fallback (no more `comp_for_rel()` / piecewise correction language).
- [x] 2.4 `pytest tests/test_export_plate_frame_alignment.py` passes. Full suite `pytest` reports `473 passed, 11 skipped (GPU-only)` — no regressions.

## 3. DaVinci PTS-gap offset audit

- [x] 3.1 User's test clip (DaVinci export) had `PTS_GAP_KEYFRAME` active — Fusion console reported the `PTS gap correction active: keyframe=... shifting all keyframes by -1 comp frame` diagnostic line.
- [x] 3.2 User exported with the current code (`pts_gap_offset = -1` active) and observed the blur landing 1 frame *ahead* of the plate — same direction the MP4 was off by before the §2 fix. Visual evidence sufficed; no screenshot step needed.
- [x] 3.3 / 3.4 Direct comparison step skipped per the user's preferred path: the symmetry with the MP4 bug (same direction, same rationale in the code comments) is strong enough evidence to remove the correction entirely rather than binary-searching through `KEYFRAME_OFFSET_OVERRIDE`.
- [x] 3.5 Removed the `pts_gap_offset` branch end-to-end: (a) `resolve_script.py` — dropped `PTS_GAP_KEYFRAME` / `pts_gap_offset` generation, simplified `comp_for_rel(rel) = clip_offset + rel`, dropped the `pts_gap_keyframe` parameter from `_generate_lua_script_for_clip` and `generate_fusion_scripts`; (b) `exporter.py` — removed the `_detect_pts_gap_keyframe` call and deleted the function itself, dropped the now-unused `subprocess` import; (c) `assembler.py` — removed the `_detect_pts_gap_keyframe` import and call; (d) `plate/blur.py` — removed the now-unused `pts_gap_keyframe` parameter and attribute from `PlateBlurProcessor.__init__`.

## 4. Spec alignment and archive prep

- [x] 4.1 `openspec validate fix-export-plate-frame-offset` — reports "is valid".
- [x] 4.2 Updated `specs/davinci-plate-export/spec.md`: simplified the requirement to `comp_for_rel(rel) = clip_offset + rel` with no conditional term, replaced the evidence-gate scenario with one that asserts no offset regardless of source-video origin (native or concatenated).
- [x] 4.3 `python -m pytest` → 473 passed, 11 skipped, 0 failed. `python -c "from trailvideocut.ui.app import launch; from trailvideocut.plate.blur import PlateBlurProcessor"` → imports clean.

## 5. Manual end-to-end re-verification

- [x] 5.1 User confirmed: "mp4 export works fine and plates are aligned" after the §2 fix.
- [x] 5.2 User confirmed: DaVinci export plates are aligned after the §3 removal of the `pts_gap_offset = -1` branch.
