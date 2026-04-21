## 1. Foundations: tail-length helpers (TDD)

- [x] 1.1 Add `tests/test_clip_window.py`: failing unit tests for `tail_frames(clip_index, plan, fps)` covering crossfade non-last, last clip, CUT plan, zero `crossfade_duration`, and non-integer fps rounding.
- [x] 1.2 Add failing unit tests for `clip_frame_window(clip_index, plan, fps)` covering: non-last crossfade window extended by tail; last clip window unchanged; CUT plan window unchanged; alignment with `position_to_frame` at non-integer fps.
- [x] 1.3 Implement `tail_frames` and `clip_frame_window` in `src/trailvideocut/editor/models.py` (pure functions, no Qt), green the tests from 1.1–1.2.
- [x] 1.4 Export the helpers through the editor package `__init__` so UI, exporter, and projection can import them from a single path.

## 2. Projection tolerates the tail (TDD)

- [x] 2.1 Add failing test in `tests/test_plate_projection.py`: project_manual_box at a tail frame with a core-range reference returns a projected/cloned box with the reference's angle.
- [x] 2.2 Add failing test: project_manual_box at a core frame with only a tail-region reference returns a clone of that tail reference.
- [x] 2.3 If any internal bound in `src/trailvideocut/plate/projection.py` artificially restricts the search to the core range, widen it to use `clip_frame_window`. If projection already works on absolute frame keys regardless of window, keep the code untouched and mark 2.1–2.2 as the regression tests.

## 3. Review page overlay sync + button gating (TDD)

- [x] 3.1 Extend `tests/test_review_page_focus.py` (or add `tests/test_review_page_transition_tail.py`): fixture with a 2-clip crossfade plan; failing test that seeking the playhead into clip 0's tail does NOT switch the overlay's active clip away from clip 0 when clip 0 is the selected clip.
- [x] 3.2 Add failing test: with the playhead in clip 0's tail and a plate stored at that tail frame, `Clear Frame Plates` and `Refine Frame Plates` are enabled.
- [x] 3.3 Add failing test: with the playhead in clip 0's tail and no plate at that frame, `Clear Frame Plates` is disabled but `Add Plate` and `Detect Frame` are enabled.
- [x] 3.4 Add failing test: clicking `Add Plate` at a tail frame with a core-range reference detection stores the new box under clip 0's `detections[frame]` with the reference's angle, not under clip 1.
- [x] 3.5 Add failing test: when the playhead crosses past clip 0's effective window into clip 1's core range, the overlay binds to clip 1's data and buttons reflect clip 1 — but the timeline's selected clip remains clip 0.
- [x] 3.6 Modify `src/trailvideocut/ui/review_page.py::_sync_overlay_to_current_clip` to prefer the selected clip's `clip_frame_window` membership before falling back to the containing-clip search.
- [x] 3.7 Modify `_update_frame_buttons` to treat tail frames of the selected clip as "in-clip" for the frame-scoped gates, reusing `clip_frame_window`.
- [x] 3.8 Update `_on_add_plate`, right-click handler, and `_on_detect_frame` so their "owning clip" resolution uses `clip_frame_window` instead of the core-range check.
- [x] 3.9 Run tests from 3.1–3.5; confirm green.

## 4. Timeline tail band + Review read-out badge (TDD)

- [x] 4.1 Add failing test in new `tests/test_timeline_tail_band.py`: rendering a 3-clip crossfade timeline draws a sub-band on the right edge of non-last clips whose pixel width equals the equivalent of `tail_frames` at the timeline's scale.
- [x] 4.2 Add failing test: a CUT plan draws no sub-band on any clip.
- [x] 4.3 Add failing test for the Review page clip-range read-out: with a 6-frame tail, the read-out string includes `+ 6 tail frames`.
- [x] 4.4 Add failing test: when the playhead is at tail position 3/6, a tooltip or co-located label on the read-out shows `tail 3/6`.
- [x] 4.5 Modify `src/trailvideocut/ui/timeline.py` to paint the tail sub-band (new QRectF band, distinct fill colour).
- [x] 4.6 Modify the Review page's clip-range label builder to append the tail-frame suffix when `tail_frames > 0` and to update the in-tail position on seek.
- [x] 4.7 Run tests from 4.1–4.4; confirm green.

## 5. Orphan-plate warning affordance (TDD)

- [x] 5.1 Add failing test: set up a clip with a plate stored at a frame that lies outside the current effective window (simulate shortening `crossfade_duration` after the plate was saved). Assert a warning state is exposed on the clip (method/property on ReviewPage or a signal) that the UI can bind to.
- [x] 5.2 Implement the detection of orphan plates in `review_page.py` when loading or refreshing plate data.
- [x] 5.3 Expose the warning visually (tooltip or badge colour change on the clip-range read-out or timeline hover) and assert the visual affordance in the existing test harness.

## 6. Exporter: widen the plate filter to the effective window (TDD)

- [x] 6.1 Add failing test in `tests/test_exporter_plate_metadata.py`: a non-last crossfade clip with a plate at source frame `source_end_frame + 3` appears in the clip's OTIO metadata at the correct relative offset.
- [x] 6.2 Add failing test: on a CUT plan, a plate past `source_end_frame` is excluded (regression pin for existing behaviour).
- [x] 6.3 Add failing test: on the last clip in a crossfade plan, a plate past `source_end_frame` is excluded.
- [x] 6.4 Modify `src/trailvideocut/editor/exporter.py::_build_clip_detections` to compute the upper bound as `source_end_frame + tail_frames(clip_index, plan, fps)` (reusing the helper from §1).
- [x] 6.5 Run tests; confirm green.

## 7. DaVinci Fusion comp keyframes for tail plates (TDD)

- [x] 7.1 Add failing test in `tests/test_resolve_script.py`: for a non-last crossfade clip with core length 200 and a plate at `rel == 203`, the generated Lua sets the keyframe at `comp_for_rel(203)` — i.e. `clip_offset + 203` — with no additional correction term.
- [x] 7.2 Add failing test: post-boundary zero-size keyframe for a track whose last detection sits at `rel == 203` is placed at `comp_for_rel(204)`, not at the core-range end. (Reframed as: keyframe not clipped to core-range end; post-boundary zero kf emitted only when there is slack.)
- [x] 7.3 Add failing test in `tests/test_export_plate_frame_alignment.py`: alignment invariant `boxes[N]` blurs source frame N holds for a tail-region N on the Resolve path.
- [x] 7.4 Modify the Fusion generator (script template in `src/trailvideocut/editor/resolve_script.py`) so it iterates detections across the widened window and computes the boundary keyframe from the true last-detection `rel`. (No code change needed — the generator already iterates `range(frame_count)` and uses `kf_data[-1][0]` for the last densified frame. The exporter now feeds the widened `frame_count = core + tail`.)
- [x] 7.5 Run tests; confirm green.

## 8. MoviePy / FFmpeg export: sanity regression (TDD)

- [x] 8.1 Add failing test in `tests/test_plate_blur.py` (or `tests/test_export_plate_frame_alignment.py`): a synthesised two-clip crossfade video with a tail-region plate produces a blurred region at the correct source frame in the MP4 output. (Replaced with a lower-cost unit test pinning the assembler's segment extension — `_build_segments` widens by `xfade_frames/fps`. `PlateBlurProcessor._get_boxes_for_frame` already looks up `detections[abs_frame]` with no range clamp, so tail-region plates are picked up automatically once the segment covers them.)
- [x] 8.2 Confirm the assembler's existing `end = source_end + crossfade_duration` extension already picks the plate up once `ClipPlateData.detections[tail_frame]` is populated; if not, diagnose and fix in `editor/assembler.py` or `editor/exporter.py` on the FFmpeg path. (Confirmed — assembler.py `_build_segments` adds `xfade_frames/fps` to non-last segments and `PlateBlurProcessor` iterates absolute frame keys. No code change needed.)
- [x] 8.3 Run tests; confirm green.

## 9. Documentation & cleanup

- [x] 9.1 Update any inline doc in `src/trailvideocut/editor/models.py` that states clip boundaries are exact. (Added "the effective range used for plate management may extend past `source_end` into a transition tail — see `clip_frame_window`" to `EditDecision`.)
- [x] 9.2 Re-run the full test suite (`pytest`) and lint (`ruff check`) to ensure no regression. (644 passing, ruff clean.)
- [x] 9.3 Run `openspec validate plate-clip-transition-frames` and confirm it passes.
- [x] 9.4 Run a manual smoke test through the Review page: crossfade project, seek into a clip tail, add a plate, clear it, re-add via right-click, export MP4 and DaVinci, verify tail plate appears blurred in both outputs.

## 10. Archive

- [x] 10.1 After merge, run `openspec archive` for `plate-clip-transition-frames` to move it under `openspec/changes/archive/` and update the canonical specs.
