## Why

After shipping `fix-automatic-plate-position-displacement` the preview now lands the video surface on the correct source frame N per arrow-key step. Against that newly-correct reference, the exported MP4's blur box appears **one frame ahead** of the plate — the same displacement the preview used to have, now surfaced on the export side. The most likely cause is the unconditional `lookup_frame = abs_frame + 1` added to `PlateBlurProcessor.process_segment` on 2026-04-15 (commit `aadce99`): it was validated by eye against the then-broken preview, so when the preview was "N-1 but looked like N" the export at "N+1 fetching boxes[N+2]" appeared aligned. With the preview correct, the export's excess `+1` is the only remaining offset, matching the user's observation.

The DaVinci Lua path has an analogous but conditional shift (`pts_gap_offset = -1` in `comp_for_rel`, gated on `PTS_GAP_KEYFRAME`, commit `abf88d5`) that was also validated against the old preview — it needs the same audit, even if the effect is only visible for clips that cross a PTS-gap keyframe.

## What Changes

- Establish an explicit cross-surface invariant in the spec: **`boxes[N]` is painted at visible source frame N** in every surface — preview overlay, MP4 plate-blur export, and DaVinci Fusion composition.
- Add a reproducible TDD harness that verifies the MP4 export invariant end-to-end: synthesize a short video with frame numbers burned into the pixels, export it with a plate detection at a known source frame K, decode the export at frame K, assert the blur covers the burned-in "K" pixels (not "K-1" or "K+1").
- Based on that harness, **remove the unconditional `+1` offset** in `PlateBlurProcessor.process_segment` (`src/trailvideocut/plate/blur.py:530`) and route the lookup through a centralised helper that uses the same frame key the detector writes.
- Audit the DaVinci `comp_for_rel` offset against the same invariant. If the PTS-gap branch is still justified for real Resolve behaviour, keep it but document the empirical evidence; if it was also a preview-side artifact, remove it.
- Update the stale "calibrated frame mapping" / "±1 frame union" language in the `plate-blur-export` spec to reflect the FFmpeg + direct-key pipeline (the old MoviePy MSE calibration and N-1..N+1 box union are no longer the implementation — see commits `fb842c8` → `aadce99`).

## Capabilities

### New Capabilities
<!-- None. This change tightens existing behavior. -->

### Modified Capabilities
- `plate-blur-export`: scope the primary FFmpeg `PlateBlurProcessor` path's lookup key directly to the detector's source-frame index (no `+1`) via a new requirement; leave the existing MoviePy fallback's calibrate-and-expand requirement unchanged, since that code path is still live and its self-calibrating behavior handles offsets differently.
- `davinci-plate-export`: codify the same cross-surface invariant for Fusion comp frames (via `comp_for_rel`) and state the conditions (if any) under which `pts_gap_offset` is applied, replacing the current implicit contract.

## Impact

- **Code**
  - `src/trailvideocut/plate/blur.py` — remove the `+1` in `PlateBlurProcessor.process_segment`; update the function's docstring (which currently describes the obsolete piecewise keyframe correction).
  - `src/trailvideocut/editor/resolve_script.py` — audit `comp_for_rel` / `pts_gap_offset`; change only if the harness (or manual Resolve check) proves the -1 was spurious.
  - `src/trailvideocut/editor/assembler.py` (MoviePy fallback) and the `calibrate_frame_offset` / `expand_boxes_for_drift` helpers in `blur.py` — **left untouched**. The fallback path has its own self-calibrating behaviour that wasn't reported broken.
  - `tests/test_export_plate_frame_alignment.py` — new integration test with a synthetic per-frame-coloured clip; pins the FFmpeg-path invariant.
- **Specs**: deltas to `plate-blur-export`, `davinci-plate-export`, and `frame-precise-navigation` as listed above.
- **Dependencies**: none added. Test uses the existing ffmpeg binary already required by the export pipeline.
- **User-visible behaviour**: exported MP4 blur boxes align to the plate instead of the following frame. No UI or workflow changes.
- **Risk**: the `+1` may be partially compensating for a real OpenCV mid-GOP-seek quirk on *some* clips even though the user's test shows the opposite on theirs. The TDD harness is the guardrail: if removing the offset breaks alignment on another test clip, the harness will fail and we stop.
