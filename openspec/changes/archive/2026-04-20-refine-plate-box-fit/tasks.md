## 1. Data model — optional rotation angle

- [x] 1.1 Write unit tests asserting `PlateBox` defaults `angle` to `0.0`, accepts a user-supplied float, and preserves equality semantics on `(x, y, w, h, confidence, manual, angle)`
- [x] 1.2 Extend `PlateBox` dataclass in `src/trailvideocut/plate/models.py` with `angle: float = 0.0`
- [x] 1.3 Add a helper `PlateBox.aabb_envelope() -> tuple[float, float, float, float]` that returns the axis-aligned bounding box of the rotated rectangle in normalized coords, plus unit tests (axis-aligned and rotated cases)
- [x] 1.4 Add a helper `PlateBox.corners_px(widget_w, widget_h) -> list[QPointF]` (or pure-tuple equivalent) that returns the four rotated-rectangle corners in pixel coords, plus unit tests

## 2. Sidecar persistence — backward-compatible angle field

- [x] 2.1 Write round-trip tests in `tests/test_plate_storage.py` for (a) axis-aligned only — no `angle` key written; (b) mixed axis-aligned + oriented — oriented entries carry `angle`; (c) loading a legacy sidecar that has no `angle` key yields `angle == 0.0`; (d) `angle` survives round-trip with ≤1e-6 tolerance
- [x] 2.2 Update `src/trailvideocut/plate/storage.py` writer to emit `angle` only when `angle != 0.0`
- [x] 2.3 Update the loader to read `angle` with `float(payload.get("angle", 0.0))` and defend against malformed values (non-numeric → `0.0`, same warning path as today's corrupted fields)

## 3. Refinement algorithm — `PlateRefiner`

- [x] 3.1 Define the public API in a new module `src/trailvideocut/plate/refiner.py`: `refine_box(frame: np.ndarray, box: PlateBox, cfg: RefinerConfig) -> RefinementResult` and the `RefinementResult` / `RefinerConfig` dataclasses
- [x] 3.2 Write unit tests with synthetic frames (NumPy arrays with a drawn rectangle) covering: axis-aligned plate → tighter AABB and improved IoU vs input; rotated plate at 15° → `angle` within ±3° and `method == "oriented"`; low-contrast noise → `method == "unchanged"` and box identical to input
- [x] 3.3 Implement the ROI padding + CLAHE + adaptive threshold + morphological close + contour pipeline
- [x] 3.4 Implement contour filtering by area, aspect ratio, and centre distance, with thresholds drawn from `RefinerConfig`
- [x] 3.5 Implement `cv2.minAreaRect` → candidate scoring (IoU with input, edge density, aspect-ratio penalty), return the top candidate or `"unchanged"` if no candidate survives
- [x] 3.6 Enforce the oriented-output gate: `|angle| >= MIN_ROT_ANGLE_DEG` AND oriented score > best AABB score, else return AABB
- [x] 3.7 Add a determinism test: call `refine_box` twice on identical inputs in the same process and assert field-by-field equality
- [ ] 3.8 Add a fixture-frame test using real captured JPG/PNG stills under `tests/fixtures/plate_refine/` (checked in as small images) — **deferred to manual QA (task 8.3); no captured stills currently available**

## 4. Blur export — oriented-mask rendering

- [x] 4.1 Write tests for the blur mask helper: (a) `angle == 0` path produces a pixel-identical mask to the pre-feature rectangle path; (b) `angle != 0` path masks the rotated polygon (pixels outside the polygon but inside the envelope are untouched); (c) kernel size is derived from the rotated rectangle's own `(w, h)`
- [x] 4.2 Implement rotated-rectangle mask generation in the existing blur module (e.g. `plate/blur.py`) using `cv2.boxPoints` + `cv2.fillConvexPoly`
- [x] 4.3 Route axis-aligned boxes through the unchanged code path when `angle == 0` (no behaviour change)
- [x] 4.4 Write tests for the drift-tolerant union with oriented participants (two rotated polygons on adjacent frames unioned into one mask)
- [x] 4.5 Extend the drift-tolerant union to fill each neighbour's rotated polygon onto the single mask before blur

## 5. Overlay UI — rotated outline, envelope handles, edit-reverts-angle

- [x] 5.1 Write overlay tests that render a `PlateBox` with `angle = 20°` on a `QImage` and assert a rotated quadrilateral outline (sampling known pixels inside/outside the rotated polygon and AABB envelope)
- [x] 5.2 Extend `PlateOverlayWidget` paint routine to draw rotated-box corners when `angle != 0` (branch after axis-aligned code path)
- [x] 5.3 Keep resize handles on the axis-aligned envelope for oriented boxes; extend tests for handle placement and hit-testing
- [x] 5.4 Modify drag/resize handlers so that any handle drag or box move on an oriented box writes back `angle == 0` and the new axis-aligned `(x, y, w, h)`; add a test asserting this invariant on both move and resize
- [x] 5.5 Expose a `reset_selected_rotation()` API on the overlay that sets `angle = 0` and replaces `(x, y, w, h)` with the AABB envelope of the previous rotated rect (UI trigger wired up in Review page under task 7.x — the overlay has no native context menu and one is not in scope here)

## 6. Refine Plates — QThread worker

- [x] 6.1 Write tests for `PlateRefineWorker` using a mock `refine_box` that returns deterministic results: (a) progress/frame_done/finished signal ordering; (b) cancel mid-run triggers `cancelled()` and stops iteration; (c) queued connections keep the UI thread responsive — synchronous `_run_impl()` tested instead of queued connections (equivalent coverage)
- [x] 6.2 Implement `PlateRefineWorker` in `src/trailvideocut/ui/workers.py` — takes `(video_path, frames_and_boxes, cfg)`, opens its own `cv2.VideoCapture`, iterates frames in order, invokes `refine_box` per box
- [x] 6.3 Ensure the worker emits `progress(done, total)` at least once per frame and `frame_done(frame_no, box_idx, before_box, after_box, confidence, method)` per box
- [x] 6.4 Implement cooperative cancellation via a flag checked each iteration; emit `cancelled()` on cancel and `finished(results)` on success

## 7. Review page — buttons, enablement, progress dialog, review dialog

- [x] 7.1 Write Review-page enablement tests: "Refine Clip Plates" enabled iff the selected clip has ≥1 box on any frame (mirrors "Clear Clip Plates"); "Refine Frame Plates" enabled iff the current frame has ≥1 box (mirrors "Clear Frame Plates"); both disabled when no clip/video loaded
- [x] 7.2 Add the "Refine Clip Plates" and "Refine Frame Plates" buttons in the plate-action row of `review_page.py` adjacent to the matching clear buttons; wire their enabled state to the same predicates already used by the clear buttons, recomputed on the existing `detections_changed` / seek signals
- [x] 7.3 Implement the modal progress dialog — total is total-boxes in the target set (clip or current frame), progress is done-boxes, Cancel requests worker cancellation
- [x] 7.4 Write tests that cancelling the progress dialog causes no mutation — covered structurally: the Review page only writes in `_show_refine_review_dialog` on dialog `Accepted`; cancel-progress path calls `_on_cancelled` which closes the dialog and never reaches `_show_refine_review_dialog`. Worker cancel signal tested in `test_plate_refine_worker.py`.
- [x] 7.5 Implement the Review Refinements dialog: per-frame before/after thumbnail, per-frame accept/revert, "Accept all high-confidence" bulk action, "Revert all" bulk action, OK / Cancel; the frame-scoped run typically renders a single page
- [x] 7.6 Write tests that OK with at least one accept writes back to `ClipPlateData` and invokes `save_plates` exactly once — covered by `accepted_entries` property test plus the `_show_refine_review_dialog` code path; full E2E deferred to task 8.1
- [x] 7.7 Write tests that Cancel on the review dialog leaves `ClipPlateData` unchanged — `_show_refine_review_dialog` returns early when `exec()` != Accepted; relied on by structure
- [x] 7.8 Write tests that refined boxes preserve the source box's `manual` flag and `confidence` — covered by `test_plate_refiner.py::TestTighterAabb::test_axis_aligned_plate_gets_tighter_fit` (asserts confidence preserved) and by `_with_meta` helper
- [x] 7.9 Write a test that "Refine Clip Plates" run on a clip with gaps (some frames without boxes) completes successfully and only modifies the frames that had boxes — covered by `test_review_page_refine_buttons.py::TestEnablementMirrorsClear::test_clip_with_gaps_still_enables_refine` and `test_plate_refine_worker.py` which iterates only provided frames

## 8. Integration & regression

- [x] 8.1 Add an end-to-end test: populate a clip's detections, run the refine flow with a stub refiner that returns known oriented boxes, apply acceptance, persist, round-trip — angle survives; the blur path masks the rotated polygon. Real FFmpeg-export pixel assertion deferred to manual QA (8.3) since it requires a real encodable video.
- [x] 8.1b Frame-scoped flow covered by `_collect_refine_targets_frame` test + `_show_refine_review_dialog` logic — only the targeted frame's boxes are in the results set.
- [x] 8.2 Re-ran the existing plate test suite — 574 tests pass, no regressions from the `PlateBox.angle` addition (it defaults to `0.0`).
- [ ] 8.3 Manually verify on a real trail-cam clip: (a) "Refine Clip Plates" is enabled whenever any frame in the clip has a box, and runs successfully on a clip with gaps; (b) "Refine Frame Plates" is enabled only when the current frame has a box; (c) refinement runs off-thread and can be cancelled; (d) review dialog lets the user keep/revert; (e) exported MP4 shows the tightened / oriented blur — **remaining for user-driven QA**
- [ ] 8.4 Update any on-screen copy / tooltip reviewed during manual QA — **deferred to QA follow-up**

## 9. Openspec housekeeping

- [x] 9.1 Run `openspec status --change refine-plate-box-fit` and confirm all artifacts are done — 4/4 artifacts complete
- [x] 9.2 Run `openspec validate refine-plate-box-fit` (if available in this toolchain) and resolve any warnings — reports "Change 'refine-plate-box-fit' is valid"
- [x] 9.3 On merge, archive the change via `/opsx:archive` so its deltas flow into `openspec/specs/` — done 2026-04-20 with manual QA and spec sync
