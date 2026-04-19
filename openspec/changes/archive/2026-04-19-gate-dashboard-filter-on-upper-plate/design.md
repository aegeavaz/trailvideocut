## Context

Today, every frame processed by `PlateDetector` flows through this fixed pipeline (in both `detect_frame` and `detect_frame_tiled`):

```
model output -> _filter_geometry -> _filter_phone_zones -> _filter_vertical_position
```

- `_filter_geometry` removes detections whose pixel size or aspect ratio doesn't fit a license plate.
- `_filter_phone_zones` (a.k.a. the dashboard filter) removes any plate whose center falls inside an active dashboard exclusion zone. Active zones are populated by `update_phone_zones`, which runs once per frame at the very top of `detect_frame` / `detect_frame_tiled`.
- `_filter_vertical_position` is the always-on postfilter (see existing `plate-detector` spec): when at least one surviving box has `cy < _VERTICAL_SPLIT_THRESHOLD` (= `0.5`), it drops every box with `cy >= 0.5`.

The dashboard zone is heuristically constrained to the bottom of the frame (`_PHONE_MIN_BOTTOM_FRAC = 0.85`) and to motorcycle-class detections. So practically every box `_filter_phone_zones` removes is a lower-half box.

The user reports that `_filter_phone_zones` is too aggressive in scenes where there is no upper-half plate at all — typically close-quarter or stop-and-go footage where the only visible plate is in the lower half. The user wants the dashboard filter to apply only when scene context confirms a "real road scene" — operationalised as "at least one plate in the upper half of the same frame".

Crucially, the user wants per-frame scope (not per-clip), and only the *filter behaviour* gated, not the *zone recording*. Recording must continue on every frame so the "Show Dashboard Filter" debug overlay still renders zones consistently.

## Goals / Non-Goals

**Goals:**
- Gate `_filter_phone_zones` per frame on the presence of at least one upper-half candidate (`cy < 0.5`) in the post-geometry box list.
- Keep `update_phone_zones`, `current_phone_zones`, and `ClipPlateData.phone_zones` semantics unchanged.
- Apply the gate identically in `detect_frame` and `detect_frame_tiled`.
- Reuse the existing `_VERTICAL_SPLIT_THRESHOLD = 0.5` constant — do not duplicate it.
- Keep the existing always-on `_filter_vertical_position` step intact, including its position at the end of the pipeline.
- Add tests that lock in: (a) the new retained-box behaviour, (b) recording-invariant, (c) tiled-path parity.

**Non-Goals:**
- Adding a UI toggle, CLI flag, or constructor parameter to control the gate. The gate is hard-wired at the same threshold as the vertical-position filter.
- Changing the dashboard zone heuristic (`_PHONE_MIN_BOTTOM_FRAC`, `_PHONE_MIN_AREA_FRAC`, etc.).
- Changing the `_filter_vertical_position` semantics or threshold.
- Per-clip (rather than per-frame) gating.
- Affecting the debug-overlay rendering pipeline in `review_page.py`.

## Decisions

### Decision: Use the existing `_VERTICAL_SPLIT_THRESHOLD` constant for the gate
- **Choice:** The "upper-half" condition for the gate SHALL be `cy = box.y + box.h / 2 < _VERTICAL_SPLIT_THRESHOLD`, importing the same module-level constant already used by `_filter_vertical_position`.
- **Why:** The user's intent ("at least one plate in the 50% top") matches exactly the existing threshold. Reusing the constant keeps the two notions aligned forever — if anyone ever moves the split (which the existing spec forbids without a public-API change), both filters move together.
- **Alternative considered:** Define a new constant `_PHONE_FILTER_GATE_THRESHOLD = 0.5`. Rejected: redundant; risks the two thresholds drifting out of sync.

### Decision: Gate sits between `_filter_geometry` and `_filter_phone_zones`
- **Choice:** The "is there an upper-half box?" test runs against the post-geometry list (the same list `_filter_phone_zones` would otherwise consume). If the test fails, `_filter_phone_zones` is skipped.
- **Why:** The user wants the gate to decide whether the dashboard filter runs. The geometry filter is upstream and has nothing to do with the dashboard heuristic; running the gate after geometry ensures we don't gate based on detections that wouldn't be plates anyway.
- **Alternative considered:** Gate based on the *output* of `_filter_phone_zones` (i.e., apply the filter optimistically, then revert if no upper-half survived). Rejected: more complex, requires a "trial" pass, and the asked-for semantics are about the *input* context, not the output.

### Decision: Encapsulate the gate as a tiny private method
- **Choice:** Add `_should_apply_phone_zone_filter(self, boxes: list[PlateBox]) -> bool` returning `any((b.y + b.h / 2) < _VERTICAL_SPLIT_THRESHOLD for b in boxes)`. Both `detect_frame` and `detect_frame_tiled` call:
  ```python
  if self._should_apply_phone_zone_filter(boxes):
      boxes = self._filter_phone_zones(boxes)
  ```
- **Why:** SOLID / single-responsibility: the predicate is named, testable in isolation, and the call sites stay readable. Avoids duplicating the inline expression in two pipeline call sites where it's likely to drift.
- **Alternative considered:** Push the gate inside `_filter_phone_zones` itself (early-return when no upper-half candidate). Rejected: violates SRP — `_filter_phone_zones` should just filter; the decision *whether* to filter belongs to the caller. Also makes test mocking awkward (you can't unit-test the unconditional filter behaviour in isolation).

### Decision: Recording stays unconditional
- **Choice:** Do NOT touch `update_phone_zones`, `current_phone_zones`, or the `result.phone_zones[frame_num] = list(self._phone_zones)` line in `detect_clip`. They run for every frame regardless of the gate.
- **Why:** The "Show Dashboard Filter" overlay reads zones to render the debug rectangles; gating recording would make the overlay disappear on lower-only frames, which is not what the user asked for. The existing spec ("Zone recording SHALL NOT alter filtering semantics") cuts the same way in reverse: the filter gate must not alter recording either.

### Decision: TDD — tests first
- **Choice:** Following the project's TDD convention, the implementation order is: write failing tests for the new scenarios → run them and confirm they fail against the current always-on filter → implement the predicate and the gate → run the suite green.
- **Why:** Each commit's diff stays small and reviewable; the failing-test step is concrete evidence the new tests exercise the right code path.

## Risks / Trade-offs

- [Risk] Some real false-positive plates (e.g., reflections of the rider's own dashboard plate showing up as a single lower-half detection) will now be retained, since the gate skips the filter for that frame. → **Mitigation:** This is the desired behaviour change. The user is explicitly trading false-positive suppression for false-negative reduction in lower-only frames. If it turns out to be too noisy, a follow-up change can tighten the gate (e.g., require ≥ 2 upper-half boxes, or use confidence thresholds).
- [Risk] The vertical-position postfilter and the new gate share the `_VERTICAL_SPLIT_THRESHOLD` constant. A future change that splits them needs to update one site to introduce divergence — easy to forget. → **Mitigation:** The new private predicate `_should_apply_phone_zone_filter` documents (in its docstring) the deliberate aliasing to `_VERTICAL_SPLIT_THRESHOLD`. A test that asserts equivalence locks the behaviour.
- [Trade-off] The gate uses post-geometry boxes, not post-detection boxes. A model output with raw upper-half boxes that fail geometry (too small, wrong aspect) will not satisfy the gate even though "something was detected up there". → **Mitigation:** This is intentional and consistent with how `_filter_vertical_position` already operates — both look at the post-geometry list.
- [Risk] The existing test `test_zone_recording_does_not_alter_detections` and the broader `TestPlateDetectorPhoneZoneRecording` suite use synthetic frames where the predicate may now reroute control flow. → **Mitigation:** The implementation step includes a tasks line to re-run the suite and reconcile any incidental fixture changes; the recording invariant test should still pass because recording is untouched.

## Migration Plan

No data migration. No config / sidecar / env-var changes. The gate is hard-wired and applies to the next detection run. Re-running detection on existing clips will produce a `.plates.json` with potentially more lower-only detections preserved than before; the existing schema / format is unchanged so the sidecar still loads with previous code paths.
