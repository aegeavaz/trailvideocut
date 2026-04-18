## Context

The plate detection model (ONNX via OpenCV DNN / ONNX Runtime) continues to emit false-positive boxes even after the existing filters (confidence threshold, geometry filter, phone-zone filter, temporal tracking). Empirically, in this project's footage — dashcam / action-cam mounted on a vehicle — real plates on nearby cars consistently appear in the **upper half** of the frame (road ahead, other vehicles, signage), while the **lower half** is dominated by foreground noise (own dashboard, wheel arches, hood reflections, own wiper). Temporal filtering (`min_track_length=3`) helps but does not eliminate persistent foreground false positives, because noise in the dashboard area often tracks stably across many frames.

The existing pipeline already has a well-established hook point for per-frame postfilters: `_filter_phone_zones` runs after `_filter_geometry` inside both `detect_frame` (`src/trailvideocut/plate/detector.py:174`) and `detect_frame_tiled` (`detector.py:232`). This is the natural extension point.

## Goals / Non-Goals

**Goals:**
- Drop obviously-foreground false positives using frame-level reasoning the existing per-box filters cannot express (they see one box at a time; this filter needs the whole frame's set of surviving boxes).
- Always on, zero configuration, zero UI surface, zero new parameters. The heuristic is fixed and uniform.
- Zero retraining, zero new dependencies, O(n) cost per frame.
- Fully unit-testable without a GPU or real model — the filter operates on `list[PlateBox]`.
- Compose cleanly with `exclude_phones`, temporal filter, NMS, and debug-zone recording — must not alter their outputs.

**Non-Goals:**
- Making the filter configurable (on/off flag, tunable threshold, per-clip override). The user has explicitly decided against this.
- Horizontal-position filtering (left/right). The asymmetry we observe is vertical only.
- Per-clip or per-track postfiltering. This change operates per-frame only; temporal coherence is left to the existing `_apply_temporal_filter`.
- Teaching the model anything. This is a deterministic postfilter, not a learned one.
- Changing which frames are reported — a frame with zero surviving detections continues to be omitted from `ClipPlateData.detections` (existing semantics).

## Decisions

### Decision 1: Use bounding-box center for the top/bottom test
Use `cy = box.y + box.h / 2` compared against the fixed 0.5 threshold, identically to `_filter_phone_zones` (`detector.py:517-518`).

**Alternatives considered:**
- Top edge (`box.y`) — biases against tall boxes that straddle the split.
- Bottom edge (`box.y + box.h`) — biases the other way, and would keep plates whose bottoms dip into the lower half even though they are clearly "top-half" plates.
- IoU with the top half — more robust to straddling boxes but adds complexity with no observed benefit, and diverges from the phone-zone precedent.

**Rationale:** Center-based matches the existing filter pattern, is symmetric, and behaves predictably on boxes that straddle the split line.

### Decision 2: Trigger condition is "≥1 top-half box present"
The filter is only active when at least one surviving box has its center in the top half; otherwise it is a no-op and all boxes pass through untouched.

**Alternatives considered:**
- Always drop bottom-half boxes. Rejected: would hide legitimate plates when the only plate visible happens to be near the viewer.
- Drop bottom-half boxes only if the top-half box has confidence ≥ some threshold. Rejected: adds a knob, which contradicts the decision to keep this non-configurable.

**Rationale:** Matches the user's stated heuristic exactly ("if a plate is found in the top 50%, delete the others under the 50%") and preserves behavior on frames where only lower-half plates exist.

### Decision 3: Apply per-frame inside `detect_frame` / `detect_frame_tiled`
Insert a call to `_filter_vertical_position(boxes)` as the final step in both single-pass and tiled detection, AFTER `_filter_phone_zones`.

**Alternatives considered:**
- Apply inside `_apply_temporal_filter` / `detect_clip`. Rejected: temporal filter already assumes the per-frame filters have run; applying here would leak per-frame policy into clip-level code.
- Apply as a wrapper in `ui/workers.py`. Rejected: keeps detector semantics under test, and splits related filtering logic across modules.

**Rationale:** The filter is a per-frame policy and belongs with the other per-frame filters. This also means `detect_clip` automatically inherits the behavior through its calls to `detect_frame` / `detect_frame_tiled`, and temporal tracking operates on already-cleaned input.

### Decision 4: No configuration surface — always on, 0.5 hardcoded
Do NOT add any constructor parameters, instance attributes, UI toggles, worker plumbing, or per-call arguments. The 0.5 split is a module-level constant (or an inline literal at the single call site) inside `detector.py`.

**Alternatives considered:**
- Off-by-default flag with UI toggle. Rejected: the user explicitly asked for the filter to always apply.
- On-by-default flag that can be disabled for tests or edge-case footage. Rejected: the user asked for "always" — we don't pre-emptively build escape hatches.
- Module-level constant (e.g. `_VERTICAL_SPLIT_THRESHOLD = 0.5`) vs. bare literal `0.5`. Use a named constant — it documents intent, makes tests more readable if they want to reference the same value, and is a trivial change to localize if the heuristic ever needs tuning. This is NOT the same as making it configurable; the constant is a private implementation detail.

**Rationale:** Simplest possible surface. No flags means no combinatorial matrix of "is the filter on" × "is phone exclusion on" × "is tiling on" to test or explain. The downside — no escape hatch — is accepted per the user's direction.

### Decision 5: Composition order
Order inside `detect_frame` / `detect_frame_tiled`:
1. Model inference + decoding
2. `_filter_geometry` (per-box, cheap)
3. `_filter_phone_zones` (per-box, needs zones)
4. `_filter_vertical_position` (frame-level, needs the set) ← new

**Rationale:** Cheapest filters first; the new filter needs the final post-phone-zone set to make its decision, because a phone-zone-eliminated top-half box should NOT trigger dropping of bottom-half boxes.

## Risks / Trade-offs

- **Risk:** Legitimate plate close to the camera (e.g., plate of the vehicle immediately in front, appearing in the lower half) is dropped because a distant top-half plate was detected in the same frame, and there is no user-facing off switch.
  → **Mitigation:** Documented in the proposal and risks list. If the problem shows up in practice, the remediation path is a follow-up change that either narrows the trigger condition (e.g. only drop lower boxes whose confidence is below the top box's) or reintroduces a config flag. We are accepting the risk for the initial shipping version because the user has prioritized false-positive reduction over this edge case.

- **Risk:** Temporal filter interaction — a track that alternates between surviving and being dropped (because top-half presence varies frame to frame) could get broken into sub-min-length fragments and then fully removed by `min_track_length=3`.
  → **Mitigation:** This is actually the intended behavior for persistent dashboard false positives (the occasional frame without a real top-half plate should not resurrect them). Covered by an explicit test that runs `detect_clip` across mixed frames.

- **Trade-off:** We are encoding footage-type assumptions (forward-facing dashcam) into the pipeline with no way to opt out. If this project ever ingests reverse-facing or handheld footage, results will silently degrade. Acceptable for now — current product is scoped to action-cam trail footage.

- **Risk:** Centers exactly on the split line (`cy == 0.5`) need a single, deterministic convention.
  → **Mitigation:** Use `cy < 0.5` for "top half" (strict less-than). The split line belongs to the bottom half. Document this in the spec scenario and cover it in a dedicated test.

## Migration Plan

Not applicable — additive code-only, no data migration. Because the filter is always-on and cannot be disabled, any caller (including tests) that was relying on specific lower-half detections surviving alongside upper-half detections will see a behavior change on merge. The test step in tasks.md includes a full suite run to surface any such cases before the change lands.
