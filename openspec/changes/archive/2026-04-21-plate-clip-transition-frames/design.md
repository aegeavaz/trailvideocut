## Context

Trailers built in trailvideocut can use two transition styles: `CUT` (hard cut) and `CROSSFADE` (default, `crossfade_duration = 0.2 s`). During crossfades the visible image blends frames from clip N with frames from clip N+1. Concretely:

- `editor/assembler.py::_extract_subclips` extends every non-last clip by `+crossfade_duration` at its tail: `end = min(source_clip.duration, end + plan.crossfade_duration)` (assembler.py:1008). Those tail frames are real source-video frames that end up on screen during the cross-fade.
- `editor/exporter.py` writes OTIO transitions with `half_xfade = crossfade_duration / 2` handles on each side (exporter.py:229, 272-286). DaVinci then pulls handle frames from both clips for the dissolve.

Plate data (`plate/models.py::ClipPlateData.detections: dict[int, list[PlateBox]]`) is keyed by absolute source-video frame number and associated to a clip by the `clip_index`. The Review page enforces an implicit "frame must belong to the selected clip's exact `[source_start, source_end)` window" through three places:

- `review_page.py::_update_frame_buttons` (lines 2003-2037): enables Detect-Frame, Clear-Clip/Frame, Refine-Clip/Frame only when `selected in self._plate_data` and `frame_num in self._plate_data[selected].detections`.
- `review_page.py::_sync_overlay_to_current_clip` (lines 1230-1238): switches the overlay's active clip data to whichever clip contains `current_time`, using the strict `source_start <= current_time <= source_end` check. When the playhead is in the tail, this selects clip N+1 instead of the still-selected clip N.
- `editor/exporter.py::_build_clip_detections` (exporter.py:259-261): filters detections to `src_start_frame <= f < src_end_frame`, silently dropping anything in the tail.

Consequences for the user:
1. The overlay disappears (or switches to the wrong clip) the instant the playhead enters the tail.
2. Detect-Frame / Add-Plate / Clear-Frame / Refine-Frame do nothing there even though the user can see a plate on screen.
3. Any plate that *is* placed at a tail frame gets discarded at export.
4. The user has no visible signal for how long the tail is (6 frames at 30 fps × 0.2 s, 12 at 60 fps, etc.).

Stakeholders: end users producing DaVinci-bound trailers (primary); the Fusion export path (constraint: must not break `comp_for_rel = clip_offset + rel`).

## Goals / Non-Goals

**Goals:**
- Treat each non-last CROSSFADE clip's tail `[source_end_frame, source_end_frame + tail_frames)` as part of that clip for plate management.
- Compute `tail_frames = round(crossfade_duration * fps)` once per `CutPlan`; re-use it in UI, storage, and export.
- Keep plate actions (Detect Frame, Add Plate, Clear Frame, Refine Frame, overlay visibility) available when the playhead is in the selected clip's tail.
- Show the tail visually on the timeline and surface the exact tail-frame count in the Review UI so the user knows the padding budget.
- Propagate tail plates through both MoviePy (MP4) and DaVinci Resolve (OTIO + Fusion) export without changing frame alignment.
- Preserve the invariant "`boxes[N]` blurs source frame N" (see archived `fix-export-plate-frame-offset`).
- TDD: every behaviour change has a failing test first.

**Non-Goals:**
- Pre-clip "head" region (the user's complaint is tail-only; adding a lead-in is out of scope).
- Changes to CUT-style timelines (`tail_frames == 0` by definition).
- Changes to the persisted sidecar schema or the `ClipPlateData` dataclass shape — tail plates reuse the existing `detections[frame_number]` map.
- Changing detection worker behaviour for clip-wide "Detect Clip" (still operates on the original `[source_start, source_end)` range to keep automatic-detection time bounded).
- Introducing a new Fusion node or modifier — tail frames slot into existing per-clip comps.

## Decisions

### 1. Transition-tail length derived from `CutPlan`, not per-clip state

`tail_frames(clip_index, plan, fps) -> int` returns `round(plan.crossfade_duration * fps)` when `plan.transition_style == CROSSFADE` and `clip_index < len(plan.decisions) - 1`, else `0`. The last clip and any CUT timeline have no tail.

Alternative considered: add explicit `tail_secs` fields to each `EditDecision`. Rejected because the tail is 100% derived from the plan-level `crossfade_duration` today, and storing a per-decision copy would duplicate state and risk divergence.

Rationale: matches the exact value the assembler already uses (`end += plan.crossfade_duration`), so UI, detection, and MP4 export agree by construction.

### 2. A single "effective clip window" helper

Introduce `editor/models.py::clip_frame_window(clip_index, plan, fps) -> tuple[int, int]` returning `(start_frame, end_frame_exclusive)` where `end_frame_exclusive = source_end_frame + tail_frames(...)`. Every gate — button enablement, overlay sync, export filter, projection — calls this helper.

Alternative considered: inline the `+tail` arithmetic at each site. Rejected as it spreads a policy decision across UI + editor + exporter; a single helper lets future changes (e.g., adding a head) land in one place.

### 3. Overlay sync picks the "owning" clip, preferring the selected one

Current behaviour: `_sync_overlay_to_current_clip` iterates clips and stops at the first whose `[source_start, source_end]` contains `current_time`. New behaviour:

1. If the currently selected clip's `clip_frame_window(...)` contains the current frame, keep the selected clip active.
2. Otherwise fall back to the existing "first clip whose window contains the frame" search, using the widened window.
3. If no clip window contains the frame, fall back to the existing "no active clip" state.

This resolves the overlap ambiguity at the tail/head boundary without changing who the user explicitly picked.

Alternative considered: always pick the clip whose core range contains the frame (i.e., ignore tails for overlay sync). Rejected because that makes the selected clip's overlay vanish the moment the playhead crosses `source_end`, which is exactly the current bug.

### 4. UI affordance: shaded tail band + badge

- Timeline renders the tail as a narrower, lighter-coloured band attached to the right edge of each non-last crossfade clip.
- Review page's clip-range read-out gains a suffix `+ N tail frames` (e.g., `00:12.300 - 00:14.800 + 6 tail frames`), derived from `tail_frames(...)` and shown only when > 0.
- Review page's Add-Plate / Detect-Frame buttons show a tooltip "`Current frame is in transition tail of clip N (frame X of Y)`" when the playhead is inside the tail, so the user always knows the bound.

Alternative considered: a full "transition zone" between clips rendered as a third band. Rejected because it complicates timeline hit-testing (which clip owns a click?) and duplicates the selected-clip affordance.

### 5. Export: widen the filter window, do not shift keyframes

In `_build_clip_detections(cpd, src_start_frame, src_end_frame)`, widen the upper bound to `src_end_frame + tail_frames` for non-last crossfade clips. For the OTIO path, Fusion's `comp_for_rel(rel) = clip_offset + rel` is computed against the extended `source_range` the exporter uses for the Resolve clip (same as MoviePy). Tail frames fall within the clip's Fusion comp range and keyframes land at the correct composition frame.

Critical invariant (archived `fix-export-plate-frame-offset`): no additive offset beyond `clip_offset`. The design preserves this — we widen the *filter*, not the mapping.

Alternative considered: emit tail plates in the *next* clip's comp (as a head region). Rejected because (a) it contradicts the user's mental model (they added the plate on clip N), and (b) it would require a head-region design for that other clip, expanding scope.

### 6. MoviePy export is already correct once data is stored

`editor/assembler.py` already extends the tail at extraction time. The MoviePy blur path reads `ClipPlateData.detections` by absolute frame number. Once tail plates are stored with the correct frame key, no additional assembler change is needed — only a sanity test to prove it.

### 7. Manual plate projection across the tail

`plate/projection.py::project_manual_box` uses nearest-neighbour detections to seed a manual plate. No change to its internals, but callers now pass the widened frame range, so projection naturally works across the tail boundary. Add a test where the reference detection is at `source_end_frame - 2` and the target is `source_end_frame + 3`.

### 8. Test-first order (TDD)

1. Failing unit test in `tests/test_cut_points.py` (or new `test_clip_window.py`) for `tail_frames` and `clip_frame_window`.
2. Failing unit test for `_update_frame_buttons` gate through an in-process `ReviewPage` fixture using `pytest-qt` patterns already in the repo (`test_plate_frame_actions.py` as a template).
3. Failing integration test for `_sync_overlay_to_current_clip` over a two-clip plan with crossfade.
4. Failing export tests: `test_export_plate_frame_alignment.py` gains a case with a tail plate; `test_exporter_plate_metadata.py` verifies the metadata entry; `test_resolve_script.py` verifies the Fusion keyframe.
5. Implementation lands per task, turning each test green.

Each test must fail first for the right reason — this is the project's standing rule (see memory: "Prefer root-cause diagnosis").

## Risks / Trade-offs

- [Ambiguity at the tail/head boundary between two crossfading clips] → Overlay sync rule (Decision 3) prefers the selected clip; if the user jumps the selection to clip N+1 the overlay follows. Documented in the new spec.
- [Fusion keyframe drift if `clip_offset` is computed from the non-extended range] → Guarded by an existing explicit-invariant test in `test_resolve_script.py`; this change adds a new test case that proves `comp_for_rel` still equals `clip_offset + rel` for a tail frame.
- [User changes `crossfade_duration` after placing tail plates] → Tail plates at frames now outside the new tail become orphans. Mitigation: the existing "out-of-range" truncation already fires at export for CUT timelines; we extend the Review UI to warn (`badge + tooltip`) when stored plates exist outside the current effective window.
- [Performance: `_update_frame_buttons` runs on every seek] → `clip_frame_window` is O(1); no measurable overhead.
- [Regression in existing specs] → Each modified spec gets a delta with explicit ADDED/MODIFIED requirements so reviewers can diff cleanly.

## Migration Plan

No data migration needed — tail plates reuse existing `ClipPlateData.detections`. Rollback is trivial: revert code changes; any tail-frame plates that were persisted remain in the sidecar but are filtered out at export exactly as before (i.e., silently dropped, matching pre-change behaviour). No schema change, no one-way door.

## Open Questions

- Should "Detect Clip" include the tail by default? Current decision: no (keeps scan time predictable). Revisit after first user test.
- Should the tail badge appear when `crossfade_duration == 0`? No — it is only shown when `tail_frames > 0`, so CUT timelines see no UI change.
