## Context

The DaVinci Resolve plate-blur generator emits per-frame `XBlurSize` keyframes for each plate. The current implementation pins the value to `[1.0, 2.0]`, with the smallest plate area in the clip mapped to 1.0 and the largest to 2.0 (linear interpolation between).

There are two code paths that emit XBlurSize, and both currently encode the same `[1.0, 2.0]` range:

1. **Offline Lua-script generator** (`src/trailvideocut/editor/resolve_script.py`):
   - Module constants: `_BLUR_SIZE_MIN = 1.0`, `_BLUR_SIZE_MAX = 2.0`.
   - Used inside `_compute_blur_sizes(...)` which precomputes one value per `(track_index, frame)` and `_generate_lua_script_for_clip(...)` which writes the `BezierSpline` keyframes.

2. **In-Resolve Python automation script** (also in `resolve_script.py`):
   - The body of `apply_blur_for_clip(...)` is emitted as a string into the generated `_resolve_plates.py` companion script. It re-implements the auto-scaling inline, with hard-coded literals `1.0` and `1.0 + (...) / area_span` (so the implicit ceiling is `2.0`).

Empirically, plates blurred at `XBlurSize=1.0` (the current floor for the smallest plate in any given clip) remain partially legible after Fusion applies the blur. The fix is a vertical shift of the entire range: `[1.0, 2.0] → [1.5, 2.5]`. The dynamic range (1.0) is preserved so relative scaling between small and large plates in the same clip stays the same.

Tests in `tests/test_resolve_script.py` currently assert the old boundary values for the smallest / largest / all-equal-area scenarios; these will need to track the new range.

## Goals / Non-Goals

**Goals:**
- Replace the `[1.0, 2.0]` XBlurSize range with `[1.5, 2.5]` in both code paths.
- Keep the auto-scaling shape unchanged: linear interpolation, smallest-area → floor, largest-area → ceiling, all-equal → floor.
- Keep both code paths in sync by sourcing the values from a single place where possible.
- Update the davinci-plate-export spec and tests to reflect the new range.

**Non-Goals:**
- Changing the dynamic range (still 1.0 wide).
- Adding user-configurable blur strength, a CLI flag, or a setting in the UI.
- Touching MediaIn/MediaOut wiring, mask geometry, keyframe densification, or boundary-keyframe handling.
- Re-running historical exports — the new range only affects newly generated `.py` / Fusion comps.

## Decisions

### Decision: Shift the range as a constant change, not as a multiplier
- **Choice:** Change `_BLUR_SIZE_MIN` from `1.0` to `1.5` and `_BLUR_SIZE_MAX` from `2.0` to `2.5`.
- **Why:** The existing arithmetic (`min + t * (max - min)`) trivially produces the new range without any structural change. The implementation is one line per code path.
- **Alternatives considered:**
  - *Add an additive bias of `+0.5` after computing the existing 1.0–2.0 value.* Rejected: introduces a magic number that obscures the intent; harder to spot in code review.
  - *Make the range configurable via a constructor parameter or env var.* Rejected: YAGNI — there is no second consumer that wants a different range, and we have no signal that the range will change again.

### Decision: Keep the inline literals in the in-Resolve script body in sync by hand
- **Choice:** Update the literals in the embedded `apply_blur_for_clip` Python script body (`1.0 + (...) / area_span` → `1.5 + (...) / area_span` and the all-equal fallback `1.0` → `1.5`).
- **Why:** The embedded script is a string template that runs inside the Resolve process — it cannot import module constants from `trailvideocut`. The two paths have always been kept in sync manually, and adding a templating layer for two literals is overkill.
- **Mitigation:** Add a focused test that asserts the embedded script body contains `1.5` in the expected positions, so a future divergence is caught.
- **Alternatives considered:**
  - *Build the embedded script body via `str.format` substituting the constants.* Rejected: the embedded body already uses `{{` / `}}` escape sequences for Fusion-generated braces; mixing real `.format` substitutions with those escapes is fragile.

### Decision: TDD ordering — update tests first, then implementation
- **Choice:** Follow the project's TDD methodology. First update the failing scenarios in `tests/test_resolve_script.py` to expect 1.5 / 2.5. Confirm the tests fail with the current implementation. Then update `_BLUR_SIZE_MIN` / `_BLUR_SIZE_MAX` and the embedded literals.
- **Why:** Keeps the change reviewable: each commit's diff is small and the test failure proves the assertion changed for the right reason.

## Risks / Trade-offs

- [Risk] A user who has a partially-completed timeline produced with the old `[1.0, 2.0]` range and re-runs the export will get a discontinuity in blur strength on the same plate sizes. → **Mitigation:** None needed; this is the intended behavioural change. The user is opting into a stronger blur by re-exporting.
- [Risk] The two code paths drift again in the future (someone updates the constants but not the embedded literals, or vice versa). → **Mitigation:** The new test that asserts the embedded script body literally contains `1.5` will catch this on the next CI run.
- [Trade-off] The midpoint of the new range (2.0) coincides numerically with the ceiling of the old range. Anyone reading historical Fusion comps and comparing to new ones may be momentarily confused. → **Mitigation:** None needed beyond the proposal/spec text recording the change.

## Migration Plan

No data migration. The change applies on the next DaVinci export. There is no persisted XBlurSize value anywhere in the project's sidecar files — the values live exclusively in the generated Fusion comps / Lua scripts, which are regenerated on every export.
