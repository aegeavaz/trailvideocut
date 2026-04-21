## Why

Plate boxes support a rotation `angle` (degrees, CCW) that the preview overlay and MP4 blur path already honor, but the DaVinci Resolve export silently drops this field: `_build_clip_detections()` in `exporter.py` serializes only `{x, y, w, h}`, and neither the offline Fusion Lua generator nor the in-Resolve Python companion script writes the mask's `Angle` input. As a result, every rotated plate is blurred as if axis-aligned in Resolve — the mask slides off the oriented plate and uncovers the license number the user explicitly angled the box to hide.

## What Changes

- Include `angle` (float, degrees) in the per-frame plate dict produced by `_build_clip_detections()`, so OTIO metadata and the Fusion Lua/Python generators receive the same payload.
- Propagate `angle` through `_group_into_tracks()` and the densification step in `resolve_script._generate_lua_script_for_clip()`, emitting a keyframed `Angle` spline on each track's `RectangleMask`, with matching zero-padding boundary keyframes consistent with the existing Center/Width/Height treatment.
- Propagate `angle` through the in-Resolve Python automation path in `apply_blur_to_clip()` (`_SCRIPT_TEMPLATE`), setting the `Angle` input per frame.
- Convert angle from the PlateBox convention (degrees CCW, image-space Y-down) to Fusion's `RectangleMask.Angle` convention (degrees, Y-up) so the exported mask matches the on-screen preview orientation. Boxes with `angle == 0.0` SHALL produce numerically identical exports to today (no Angle keyframes emitted, or a constant-zero spline — decided in design.md).
- Extend `tests/test_exporter_plate_metadata.py` and add a Lua-output test to cover rotated plates and prevent future regression.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `davinci-plate-export`: OTIO plate metadata now includes per-box `angle`; the generated Fusion composition rotates each RectangleMask to match the preview orientation.

## Impact

- Code:
  - `src/trailvideocut/editor/exporter.py` (`_build_clip_detections`)
  - `src/trailvideocut/editor/resolve_script.py` (`_group_into_tracks`, `_generate_lua_script_for_clip`, `_SCRIPT_TEMPLATE.apply_blur_to_clip`)
- Specs: `openspec/specs/davinci-plate-export/spec.md` (delta).
- Tests: `tests/test_exporter_plate_metadata.py`; new or extended resolve-script test asserting `Angle` keyframes in the generated Lua.
- No changes to UI, OTIO schema version, or CLI surface. Existing `.otio` files without `angle` remain readable (default `0.0`).
- Third-party: relies on Fusion `RectangleMask.Angle` input, available on all supported Resolve versions (Studio 20+).
