## Why

Empirically, the current XBlurSize range (1.0 → 2.0) produces under-blurred plates on the small end: at XBlurSize=1.0 the smallest plates are still legible after the Fusion blur is applied. Bumping the floor to 1.5 and the ceiling to 2.5 keeps the same dynamic range (1.0) and the same relative scaling behavior, while raising the absolute blur strength so even the smallest detected plate is unreadable in the exported timeline.

## What Changes

- Update the auto-scaling range used by the DaVinci Resolve plate-blur generator from `[1.0, 2.0]` to `[1.5, 2.5]` so that:
  - Smallest plate area in a clip → `XBlurSize = 1.5`
  - Largest plate area in a clip → `XBlurSize = 2.5`
  - Linear interpolation continues for intermediate sizes
  - Single-area / all-equal-areas case → `XBlurSize = 1.5` (the new floor)
- Apply the same range in both code paths that emit XBlurSize values: the Lua-script generator (`_compute_blur_sizes` / `_generate_lua_script_for_clip`) and the in-Resolve Python automation script (`apply_blur_for_clip`-equivalent block).
- Update the existing davinci-plate-export spec requirement that pins the range to 1.0 / 2.0.
- Update tests that assert the boundary blur values.

No behavioural change for anyone who has not yet exported with plate blur — only newly generated `.py` / Fusion comps shift to the higher range.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `davinci-plate-export`: the "Blur size auto-scaling by relative plate area" requirement changes its numeric range from 1.0 / 2.0 to 1.5 / 2.5.

## Impact

- Code:
  - `src/trailvideocut/editor/resolve_script.py` — module constants `_BLUR_SIZE_MIN`, `_BLUR_SIZE_MAX`, plus the inline `1.0` floor in the embedded `apply_blur_for_clip` Python script body.
- Tests:
  - `tests/test_resolve_script.py` — any assertion that pins the floor / ceiling at 1.0 / 2.0 (e.g. smallest-plate, largest-plate, all-equal-area scenarios).
- Specs:
  - `openspec/specs/davinci-plate-export/spec.md` — "Blur size auto-scaling by relative plate area" requirement and its three scenarios.
- No external API surface, no config file format change, no migration: the range is hard-coded and applies to the next export.
