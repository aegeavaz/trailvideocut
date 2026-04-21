## 1. Failing tests first (TDD)

- [x] 1.1 In `tests/test_exporter_plate_metadata.py`, add `test_angle_serialized_for_rotated_plate` asserting the per-frame dict built by `_build_clip_detections()` contains `angle` with the input box's angle value, for both a rotated box (e.g. `angle=22.5`) and an axis-aligned one (`angle=0.0`). Run the suite and confirm only this new test fails.
- [x] 1.2 Add `tests/test_resolve_script_angle.py` with `test_angle_spline_emitted_for_rotated_track`: feed `_generate_lua_script_for_clip()` a clip whose plate track has `angle=30.0` across several frames, assert the returned Lua contains exactly one `mask1.Angle = BezierSpline({})` line and at least one `mask1.Angle[comp_for_rel(<N>)] = -30.0` line (matching the Y-down→Y-up sign flip).
- [x] 1.3 In the same new test module, add `test_angle_spline_zero_for_axis_aligned_track` asserting that when every detection has `angle=0.0`, every emitted `mask1.Angle[...] = ...` keyframe value is exactly `0.0`.
- [x] 1.4 In the same new test module, add `test_angle_boundary_keyframes_are_zero` asserting that when a track starts mid-clip and ends mid-clip, the pre-boundary and post-boundary keyframes emit `mask1.Angle[...] = 0` (mirroring the existing Width/Height zero boundaries). Boundaries land at `first_detection - _NEAREST_WINDOW - 1` and `last_detection + _NEAREST_WINDOW + 1` once densification is accounted for.
- [x] 1.5 Add `test_legacy_dict_without_angle_defaults_to_zero` covering the reader path: call `_generate_lua_script_for_clip()` with a plate dict that has no `angle` key (simulating a pre-change OTIO) and assert the generated Lua treats it as `angle=0.0` (no crash, zero-valued Angle keyframes).

## 2. Serialize angle in `_build_clip_detections`

- [x] 2.1 In `src/trailvideocut/editor/exporter.py`, add `"angle": float(b.angle)` to the dict comprehension at exporter.py:161-169.
- [x] 2.2 Re-run `tests/test_exporter_plate_metadata.py`; confirm 1.1 now passes.

## 3. Emit Angle spline in offline Lua generator

- [x] 3.1 In `src/trailvideocut/editor/resolve_script.py`, add a module-level helper `_plate_angle_to_fusion(angle: float) -> float` returning `-angle`, with a one-line comment referencing the Y-down→Y-up coordinate inversion (same reason `cy` is inverted a few lines above).
- [x] 3.2 In `_group_into_tracks()`, ensure the per-frame box dict carried through to the densification step includes `angle` (default `0.0` if missing, for forward-compat with legacy OTIO inputs). — already pass-through; `box.get("angle", 0.0)` in 3.3 provides the default.
- [x] 3.3 In `_generate_lua_script_for_clip()`, extend the `kf_data` tuple from `(frame, cx, cy, w, h)` to `(frame, cx, cy, w, h, a)` where `a = _plate_angle_to_fusion(box.get("angle", 0.0))`.
- [x] 3.4 After the existing "Animate mask height" block, emit an analogous "Animate mask angle" block: `mask_var.Angle = BezierSpline({})`, pre-boundary `= 0` keyframe if `first_kf_frame > 0`, per-frame `= a`, post-boundary `= 0` if `last_kf_frame + 1 < frame_count`.
- [x] 3.5 Re-run `tests/test_resolve_script_angle.py`; confirm 1.2–1.5 now pass.

## 4. Emit Angle in in-Resolve Python automation path

- [x] 4.1 In the `_SCRIPT_TEMPLATE` string, locate `apply_blur_to_clip()` (resolve_script.py:668-763). Inside the per-frame loop (around resolve_script.py:755-757), compute `angle = -float(box.get("angle", 0.0))` and emit `mask.SetInput("Angle", angle, frame_num)` alongside the existing Center/Width/Height calls.
- [x] 4.2 Add a test that renders `_SCRIPT_TEMPLATE` and asserts the embedded `apply_blur_to_clip` source references `"Angle"` and `box.get("angle", 0.0)`, guarding both the key name and the legacy-default behavior.

## 5. Cross-cutting verification

- [x] 5.1 Run the full test suite (`pytest`) and confirm no regressions elsewhere. — 605 passed, 11 skipped (unchanged).
- [x] 5.2 Run `openspec validate export-davinci-blur-rotation --strict` and confirm it passes.
- [x] 5.3 Manual acceptance on WSL: take a short clip with at least one clearly-rotated (≥20°) manual plate, export to DaVinci with plate blur + auto-apply, and visually verify in Resolve that the mask is tilted to cover the plate — not the axis-aligned envelope. Record the clip name/frame used in the commit message for future verification.
- [x] 5.4 Manual acceptance edge cases: (a) a clip where one plate is rotated and another is axis-aligned in the same frame range, (b) a rotated plate whose track starts mid-clip (checks boundary keyframes). Both must render correctly.

## 6. Wrap-up

- [x] 6.1 Update `openspec/specs/davinci-plate-export/spec.md` by applying the delta via `openspec archive export-davinci-blur-rotation` once all code tasks are complete and merged.
- [x] 6.2 Commit with message `Export DaVinci blur with plate rotation angle (openspec: export-davinci-blur-rotation)`.
