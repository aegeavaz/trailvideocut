## Context

`PlateBox` (src/trailvideocut/plate/models.py:7-25) carries a rotation `angle` (float, degrees) that drives the preview overlay and the MP4 blur pipeline (`_apply_oriented_blur` in src/trailvideocut/plate/blur.py:201-240). The DaVinci export path, however, was wired when `PlateBox` was still axis-aligned and has not been updated.

Concretely:
- `_build_clip_detections()` (src/trailvideocut/editor/exporter.py:141-170) flattens each box to `{x, y, w, h}` only. The resulting dict is reused as (a) OTIO clip metadata (`trailvideocut.plates`) and (b) the input to the Fusion Lua generator.
- `_generate_lua_script_for_clip()` (src/trailvideocut/editor/resolve_script.py:101-335) emits keyframed splines for `Center`, `Width`, `Height`, and `XBlurSize` on each track's `RectangleMask`/`Blur`. There is no spline for `Angle`.
- The in-Resolve Python automation path `apply_blur_to_clip()` (src/trailvideocut/editor/resolve_script.py:668-763, embedded via `_SCRIPT_TEMPLATE`) has the same omission.

**Rotation convention (verified by reading the code, not assumed):**
- `PlateBox.corners_px()` (models.py:43-68) applies the standard 2D rotation matrix `(rx = lx·cos − ly·sin, ry = lx·sin + ly·cos)` in pixel space where **Y points down**. A positive `angle` therefore rotates the rectangle **clockwise on screen**. The overlay and oriented-blur paths both consume these corners.
- Fusion's `RectangleMask.Angle` is in degrees with positive values rotating **counter-clockwise on screen** in its Y-up image space.
- Therefore the mathematically correct conversion for visual parity is `fusion_angle = -box.angle`. This sign flip is the same transform already applied to Y (`cy_fusion = 1.0 - (box.y + box.h/2)`) — both stem from the Y-axis inversion between the two coordinate systems.

## Goals / Non-Goals

**Goals:**
- DaVinci-exported blur masks visually overlap the plate at every rotation angle, matching the preview overlay to within sub-pixel accuracy at the mask centre.
- Zero regression for axis-aligned (`angle == 0.0`) exports — byte-identical output where feasible, otherwise a trivially equivalent constant-zero `Angle` spline.
- Single source of truth for the plate-payload shape: OTIO metadata, offline Lua, and in-Resolve Python all consume the same `{x, y, w, h, angle}` dict.
- The Lua and in-Resolve Python generators stay in lock-step — a new test asserts the Angle spline appears in both outputs.

**Non-Goals:**
- Adding any new UI affordance (angle editing already exists in the plate overlay).
- Introducing a new OTIO schema version or bumping persistence file format on disk.
- Honoring any transform beyond rotation (skew, shear, per-corner distortion).
- Auto-applying rotation to already-exported projects — this fix only affects new exports.

## Decisions

### Decision 1: Include `angle` in the serialized payload, default 0.0 on read

Add `"angle": float(b.angle)` to the dict produced by `_build_clip_detections()` (the sole place the payload is built). Readers that deserialize plate metadata SHALL treat a missing `angle` key as `0.0` so pre-existing `.otio` files continue to round-trip and replay correctly.

**Alternative considered:** Bumping the OTIO metadata schema version and refusing to read old files. Rejected — the field is purely additive and defaulting is cheap and safe.

### Decision 2: Emit `Angle` as a keyframed `BezierSpline` alongside `Width`/`Height`

Mirror the existing Width/Height code path:
- `{mask_var}.Angle = BezierSpline({})`
- For each densified keyframe `(frame, cx, cy, w, h, angle_fusion)`, emit `{mask_var}.Angle[comp_for_rel({frame})] = {angle_fusion}`.
- Boundary keyframes (one frame before the first detection and one frame after the last, when within range): emit `Angle = 0` to match the zero-size Width/Height boundaries. Zero angle combined with zero width/height is a no-op, but keeping the spline shape uniform avoids asymmetric keyframe counts that confuse Fusion's hold behavior.

**Alternative considered:** Emit the `Angle` spline only when at least one detection in the track has a non-zero angle. Rejected — the conditional complicates both generators and the test surface; a constant-zero spline is cheap (one entry per frame, a few bytes per line) and keeps the generated script shape predictable. The optimization is premature.

### Decision 3: Angle conversion `fusion_angle = -plate_angle`

Apply the sign flip inside the densification step (the single point where frame-level fields are computed), in both `_generate_lua_script_for_clip` and `apply_blur_to_clip`. Adding a named helper `_plate_angle_to_fusion(angle: float) -> float` in `resolve_script.py` documents the convention and gives tests something explicit to assert against.

**Alternative considered:** Apply the sign flip at serialization time, so the `.otio` metadata already stores Fusion-native angles. Rejected — OTIO metadata is our canonical record of "what plate is where in source footage"; it should reflect the in-app PlateBox convention, not a consumer-specific one. Per-consumer conversion at emit time keeps the invariant clean.

### Decision 4: TDD-first — write the failing Lua/metadata assertions before touching `_build_clip_detections`

Two tests lead the implementation:
1. `test_exporter_plate_metadata.py::test_angle_serialized` — asserts the per-frame dict carries `angle` (including for legacy angle-less inputs where the value SHALL be `0.0`).
2. A new `tests/test_resolve_script_angle.py::test_angle_spline_emitted` — asserts the generated Lua contains `mask1.Angle = BezierSpline({})` and at least one `mask1.Angle[comp_for_rel(<N>)] = <value>` line that matches `-plate_angle` for the input.

These exercise exactly the two seams where angle is dropped today and will fail on `main` before any code change.

## Risks / Trade-offs

- **[Risk] Fusion `RectangleMask` `Angle` input name differs across Resolve versions** → Mitigation: verified via Fusion documentation and Resolve 18/20 release notes that the input is named `Angle` and is animatable on `RectangleMask`. The test suite cannot exercise Resolve itself; we rely on manual verification on a rotated plate export as an acceptance step in tasks.md and will fall back to a mask-level `Transform` wrapper if `Angle` turns out to be unavailable on a supported version.
- **[Risk] Sign-convention confusion regresses silently** → Mitigation: (a) the `_plate_angle_to_fusion` helper is unit-tested with a positive and negative case, (b) tasks.md requires a manual visual-parity check against the preview before marking the change done.
- **[Trade-off] Always emitting a full Angle spline, even for axis-aligned clips, increases generated Lua size by ~1 line per keyframe** → Accepted; script size is tiny compared with OTIO + media references and this avoids a conditional code branch that historically drifts between the Lua and in-Resolve Python paths.
- **[Risk] Pre-existing `.otio` files written before this change lack `angle`** → Mitigation: all readers (`_group_into_tracks`, `apply_blur_to_clip`) default missing `angle` to `0.0`, preserving existing behavior.

## Migration Plan

No data migration required. On first export after the upgrade, plate metadata gains an `angle` field; older OTIO files remain valid and behave as though every box had `angle = 0.0`. Rollback is a straight revert of the three edited source files — no state on disk needs rewriting.
