## Why

When the trailer timeline uses crossfades, the assembler extends each non-last clip's tail into the next clip by `crossfade_duration` seconds, and DaVinci Resolve pulls additional head/tail handle frames through the transition. Plates visible during those transition-tail frames still need to be blurred, but the Review page only lets the user detect, add, clear, or refine plates on frames that fall inside the selected clip's exact `[source_start, source_end)` range. Users have to guess how many frames past the clip end to cover, and even when they add a manual box at a "post-clip" frame, the per-frame buttons (Clear Frame, Refine Frame) stay disabled because the gating logic refuses to treat those frames as belonging to the selected clip. Export then silently truncates any plate past `source_end` (`_build_clip_detections` filters to `src_start_frame <= f < src_end_frame`), so the plate is lost from the DaVinci comp even if it was created.

## What Changes

- Introduce an explicit **clip transition tail** concept: the frame range `[source_end, source_end + crossfade_duration)` of every non-last crossfade clip, whose size is derived from the active `CutPlan.crossfade_duration` and the video fps.
- Extend the plate-editing gate in `review_page.py::_update_frame_buttons` and `_sync_overlay_to_current_clip` so a frame inside the selected clip's transition tail is treated as "in-clip" for Detect Frame, Add Plate, Clear Frame Plates, Refine Frame Plates, and plate-overlay visibility. The selected clip does not change as the playhead enters its tail.
- Show the transition-tail region on the Review timeline and on the clip-range read-out (e.g., distinct shading plus a "+N tail frames" badge) so the user sees exactly how many extra frames they can safely plate.
- Make plate storage tolerate tail frames: manual plates added inside a clip's tail are saved against that clip's `ClipPlateData.detections` at their absolute source-frame key; projection (`project_manual_box`) and overlay sync follow suit.
- Extend the DaVinci/OTIO export path (`_build_clip_detections`, Fusion comp math) to include tail-region plates in the owning clip's metadata and Fusion composition without shifting existing frame alignment. MoviePy export already iterates the extended subclip range and will pick tail plates up once they are present in `ClipPlateData.detections`.
- Add regression tests covering: button enablement inside the tail, add/clear/refine on a tail frame, export of a tail plate in both MP4 and DaVinci pipelines, and the timeline badge rendering.
- Non-goal: this change does not introduce a pre-clip "head" region (the user's request is about frames after the clip); it also does not change the exporter's handling of `CUT` transitions, which have no tail.

## Capabilities

### New Capabilities
- `plate-clip-transition-tail`: defines the transition-tail frame band derived from `crossfade_duration`, specifies which plate actions are available there, and specifies how tail-region plates are exported.

### Modified Capabilities
- `plate-overlay-ui`: the button-enablement and overlay-sync requirements must now include the selected clip's transition tail, not only `[source_start, source_end)`.
- `plate-clearing-actions`: "Clear Frame Plates" and "Refine Frame Plates" gates must recognise tail frames as part of the selected clip.
- `plate-detection-workflow`: single-frame detection is allowed on tail frames of the selected clip.
- `davinci-plate-export`: tail-region plates must be emitted in the owning clip's Fusion comp with correct `comp_for_rel` alignment, preserving the existing "no additive offset beyond `clip_offset`" invariant.
- `plate-blur-export`: the MP4 export filter must keep plates at tail frames (no truncation at `source_end`).

## Impact

- Code:
  - `src/trailvideocut/editor/models.py` — helper to compute tail length from `CutPlan.crossfade_duration` and fps.
  - `src/trailvideocut/ui/review_page.py` — `_update_frame_buttons`, `_sync_overlay_to_current_clip`, `_on_add_plate`, `_on_detect_frame`, `_on_clear_frame_plates`, `_on_refine_frame_plates` gating.
  - `src/trailvideocut/ui/timeline.py` — clip-range rendering adds tail shading and frame-count badge.
  - `src/trailvideocut/ui/plate_overlay.py` — accept tail frames when selecting active clip data.
  - `src/trailvideocut/editor/exporter.py` — `_build_clip_detections` widens the filter window to include the tail for non-last crossfade clips; Fusion keyframe emission for tail frames.
  - `src/trailvideocut/plate/projection.py` — projection allowed across the tail boundary for the same clip.
- Tests:
  - New unit/integration tests in `tests/` covering the gating, projection, and export paths.
  - Existing `test_plate_frame_actions.py`, `test_export_plate_frame_alignment.py`, `test_exporter_plate_metadata.py`, and `test_resolve_script.py` must be updated to reflect the widened clip window.
- Specs: new `plate-clip-transition-tail` spec plus delta changes listed above.
- No changes to plate storage schema, persisted sidecar format, or the `ClipPlateData` dataclass shape.
- No change to CUT-style timelines (`crossfade_duration` effectively zero).
