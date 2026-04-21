## Context

Plate detection today produces axis-aligned `PlateBox` rectangles (x, y, w, h normalised 0-1) stored per-frame and persisted to a `.plates.json` sidecar. Blur export renders an axis-aligned blurred patch over each box. When the plate sits at a camera-induced angle (typical trail-cam / dash-cam footage) the AABB must cover the full rotated plate and thus blurs a large surrounding background area — or, if the original detection was already loose, leaves the plate's edges readable.

Existing image-processing assets we can lean on:
- OpenCV (`cv2`) is already a required dependency and used throughout the plate pipeline.
- NumPy is used for NMS / ROI ops.
- The review page already runs detection off-thread via a QThread worker (`ui/workers.py`) and has a progress-dialog pattern.
- Blur and overlay paths already key off `(frame_no → list[PlateBox])`.

The new feature is a **post-process** (not a detection substitute): it only refines boxes that already exist. It does **not** require the clip to be fully covered — whatever boxes are present are refined, and the user can run it per-frame (mirroring "Clear Frame Plates") or across the whole clip (mirroring "Clear Clip Plates").

## Goals / Non-Goals

**Goals:**
- Add two actions on the Review page — "Refine Clip Plates" and "Refine Frame Plates" — that mirror the enablement semantics of "Clear Clip Plates" / "Clear Frame Plates".
- Implement a self-contained refinement algorithm over the ROI of each existing box that produces a tighter-fitting region.
- Support oriented (rotated-rectangle) output when the rotation estimate is confident; otherwise keep the tighter AABB.
- Extend the data model with an optional `angle` attribute (degrees, default 0.0) that is backward-compatible with existing sidecars.
- Update blur export and overlay rendering to honour `angle`.
- Run refinement off the UI thread with progress reporting, cancellation, and a user-facing accept/revert.

**Non-Goals:**
- Re-detecting plates in frames where none were placed (this is *post* placement).
- Per-pixel plate segmentation. The output remains a quadrilateral described by centre/size/angle.
- Full perspective (4-corner homography) fit. The design supports rotated rectangles only; arbitrary trapezoid fit is explicitly deferred.
- Automatic multi-frame smoothing/tracking of refined boxes (kept to single-frame, per-box refinement; later iteration can layer temporal smoothing).
- Changing the detection pipeline or the "Detect Plates" action.

## Decisions

### 1. Refinement algorithm: bounded-search edge + contour fit, with rotated-rect consolidation

**Choice:** Inside a padded ROI around each existing box, run:
1. Grayscale + CLAHE for lighting-invariant contrast.
2. Adaptive threshold (plus a Canny/Sobel fallback) to isolate high-gradient structures.
3. Morphological close to bridge character gaps on the plate face.
4. `cv2.findContours` on the result, filtered by:
   - Area within `[0.15, 2.0]` × the original box area.
   - Aspect ratio within a plate-ish range (configurable; default `[1.5, 6.0]`).
   - Centre within the original box (Manhattan distance threshold).
5. For each surviving contour, compute `cv2.minAreaRect` → (centre, (w, h), angle). Pick the candidate that maximises a score combining IoU-like overlap with the original box, edge-density within the candidate, and penalty for extreme aspect-ratio deviation.
6. If `|angle| < θ_min` (e.g. 2°) OR the rotated-rect aspect is within tolerance of the axis-aligned best fit, return the tighter AABB (`angle = 0`). Otherwise return the oriented rect.

**Rationale:** This is a well-understood recipe that leans on OpenCV primitives we already ship. It does not require a model, GPU, or training data. It is deterministic and testable.

**Alternatives considered:**
- *Deep segmentation model (e.g. a small U-Net or SAM prompted with the box):* Best accuracy, but requires a new heavyweight dependency + weights + GPU fallback. Rejected for scope; can be added later behind the same "Refiner" interface.
- *Hough-line search for plate edges:* Works on clean plates but fragile under dirt/shadow; harder to tune. Kept as a possible secondary estimator for future iteration.
- *Direct homography / 4-point perspective fit:* Would require stable corner detection; out of scope per Non-Goals.

**Confidence / fallback:** The refiner returns a `RefinementResult { box: PlateBox, confidence: float, method: {"aabb","oriented","unchanged"} }`. If confidence < threshold, the original box is kept.

### 2. Data model: optional rotation angle, not a new class

**Choice:** Extend `PlateBox` with `angle: float = 0.0` (degrees, centred on the box centre, positive counter-clockwise in image coords — matching `cv2.minAreaRect` convention after normalisation). Box extents `(w, h)` always represent the rotated rectangle's own width/height (plate-aligned), not the AABB.

**Rationale:** Single type, single codepath. Consumers (blur, overlay, storage) branch on `angle != 0` where needed. Keeps the diff small and avoids an Either/union type.

**Alternatives considered:**
- *Separate `OrientedPlateBox` class:* duplicates serialisation and consumer code.
- *Store as 4-point polygon:* more general but over-specifies (and any 4 points no longer round-trip through `minAreaRect`). Rejected — we only need rectangles.

**Serialisation:** `angle` is written only when non-zero (reduces sidecar diff churn) and read with `angle = payload.get("angle", 0.0)`. Sidecar schema version stays additive.

### 3. UI: paired clip/frame buttons with a shared review modal

**Choice:** Two buttons in the Review page's plate action row, placed next to the matching "Clear Clip Plates" / "Clear Frame Plates" buttons:

- **Refine Clip Plates** — targets every `(frame_no, box)` pair in the selected clip's existing detections.
- **Refine Frame Plates** — targets every box on the currently displayed frame only.

Both buttons drive the same flow:
1. Open a modal progress dialog with a cancel button; a `PlateRefineWorker` QThread iterates the target set (a clip's boxes, or a single frame's boxes) and emits `frame_done(frame_no, before_box, after_box, confidence, method)` and `progress(done, total)`.
2. On completion, open the **Review Refinements** dialog: a paged before/after preview (render the original and refined boxes as overlays on the frame thumbnail) with per-frame accept / revert, plus "Accept all high-confidence" and "Revert all" bulk actions. For the frame-scoped run there is typically a single page.
3. On OK, persist the accepted refinements via the existing `save_plates()` path; on Cancel, no sidecar change.

**Enablement predicates** (re-evaluated on every detections signal the page already listens to):

- *Refine Clip Plates:* at least one frame in the selected clip has at least one box — identical to the "Clear Clip Plates" enablement predicate.
- *Refine Frame Plates:* the currently displayed frame has at least one box — identical to the "Clear Frame Plates" enablement predicate.

Full-coverage is explicitly not required. Frames without any boxes are not "refinement targets" — they are skipped during iteration because they produce no work, not because the run is gated.

**Rationale:** Gives the user the control they already have for manual edits; avoids a silent, irreversible bulk mutation. Mirrors the existing "confirm-before-destructive-action" pattern and the familiar clip/frame pairing used throughout the plate UI.

**Alternatives considered:**
- *Single button gated on full coverage:* initially proposed but rejected — clips routinely have frames without plates (e.g. plate out of view partway through), so full coverage is neither common nor required for refinement value.
- *Auto-apply with global undo:* faster UX but undo support does not exist for plate edits today; rejected.
- *Context-menu-only entry points:* harder to discover than visible buttons; rejected.

### 4. Blur export: rotated-rect mask when `angle != 0`

**Choice:** In the existing blur rendering path, when `angle != 0`, build the rotated rectangle's four corner points via `cv2.boxPoints(((cx, cy), (w, h), angle))`, draw the filled polygon into the mask with `cv2.fillConvexPoly`, apply the existing blur kernel through the mask. The drift-tolerant union box already used for AABB blur is extended to union the rotated-rect's AABB bounding envelope so union logic remains pixel-safe.

**Rationale:** The existing blur kernel-sizing logic (`max(3, min(w_px, h_px))`) and frame-keyed lookup stay unchanged; only the mask generation branches.

### 5. Overlay: rotated outline + resize handles on AABB envelope

**Choice:** When rendering a box with `angle != 0`, draw the four corner outline rotated; keep the resize handles on the **axis-aligned envelope** (simpler UX). Dragging a handle returns the box to `angle = 0` and resizes it — editing a rotated box reverts it to AABB by design (consistent with the "manual edit wins" principle). A context-menu "Reset rotation" action is provided.

**Rationale:** Rotated handles are an ergonomics rabbit hole; reverting-on-edit keeps invariants clear.

### 6. Threading, cancellation, progress

**Choice:** Reuse the existing QThread worker pattern. The worker takes a snapshot of `(video_path, frames_and_boxes)` and a shared `QVideoCapture` or a path to re-open `cv2.VideoCapture` off-thread. Per-frame decode reuses the existing decode helper. Emits are Qt-queued so the UI stays responsive. Cancel sets a flag checked each iteration.

### 7. Testing strategy (TDD)

- **Unit tests for the refiner** use synthetic frames (NumPy arrays with a drawn, possibly-rotated rectangle) for deterministic assertions on `angle`, box centre, and confidence. A separate fixture frame set (real video sample, stored as PNG in `tests/fixtures/plate_refine/`) gives realistic end-to-end checks.
- **Serialisation round-trip test** writes a refined box and reads it back; covers old-format files missing `angle`.
- **Blur mask test** renders a rotated mask and asserts pixels outside the polygon are untouched.
- **Overlay draw test** renders a rotated box to a `QImage` and checks expected edge pixels via hashing on well-known fixtures.
- **Review page test** asserts button enablement under populated/empty detections and that applying a refinement calls `save_plates` exactly once per accepted frame.
- Each layer ships its tests first and the implementation follows.

## Risks / Trade-offs

- **[Risk]** Refinement produces a *worse* box on low-contrast / cluttered plates.
  **Mitigation:** Confidence threshold + required minimum edge density; mandatory user review dialog before persisting; "Revert all" bulk action.

- **[Risk]** Oriented boxes break downstream consumers that still assume AABB.
  **Mitigation:** Additive data-model field defaulting to 0; audit blur, overlay, storage, tests, and add AABB-envelope helpers where consumers can stay AABB-aware.

- **[Risk]** Performance regresses on long clips (hundreds of frames × multiple boxes).
  **Mitigation:** Off-thread, progress + cancel, and per-box ROI sizes are small (not full-frame). Budget target: <10 ms per box on CPU.

- **[Risk]** Sidecar JSON read by an older build sees a new `angle` field.
  **Mitigation:** Only the field is added; older readers ignore unknown keys. Document the forward-compat expectation in plate-persistence spec delta.

- **[Trade-off]** Editing a rotated box in the overlay resets rotation. Users who refined and then want to nudge will lose the angle and may need to re-refine. Acceptable for v1; a future iteration can make handles rotation-aware.

- **[Trade-off]** We fit rotated rectangles only, not full perspective quads. Severely angled plates (e.g. side-view) will still leave slight fringe. Documented as a known limitation.

## Migration Plan

- No data migration required; format change is additive.
- Feature lands behind no flag — button simply appears once the branch ships.
- Rollback: revert the commit(s); existing sidecars remain readable because old readers ignore the `angle` key.

## Open Questions

- **Default confidence threshold** below which a refinement is auto-classified as "low-confidence" in the review dialog — propose `0.6` and tune on real footage during QA.
- **Dashboard-filter interaction:** should plates filtered out by the upper-half dashboard heuristic be skipped by the refiner? Proposed: yes (refiner runs only over boxes the user actually kept, which already passed any filter).
- **Keyboard shortcut** for the actions — propose `Shift+R` for Refine Clip Plates and `R` for Refine Frame Plates on the Review page; confirm during UI review.
