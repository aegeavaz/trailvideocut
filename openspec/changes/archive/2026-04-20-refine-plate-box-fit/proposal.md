## Why

After a clip's plates are detected (or manually placed), the axis-aligned blur boxes frequently overshoot the plate (wasting blur area, occluding surrounding context) or undershoot it (leaving parts of the plate readable). Plates photographed from an angle are particularly poorly covered by an AABB. Reviewers currently have no way to tighten box fit except by hand-editing each frame, which is tedious for long clips. A post-process refinement pass — invokable at either the clip or the current-frame level — would tighten fit and, where feasible, adapt the box to the plate's true rotation/shear.

## What Changes

- Add two new actions in the Review page's plate-detection action row, mirroring the existing "Clear Clip Plates" / "Clear Frame Plates" pair:
  - **Refine Clip Plates** — runs refinement over every box in the selected clip's existing detections. Frames without boxes are simply skipped; full coverage is **not** required.
  - **Refine Frame Plates** — runs refinement over every box on the currently displayed frame only.
- Enablement mirrors the clear actions: "Refine Clip Plates" is enabled when the selected clip has at least one box on at least one frame; "Refine Frame Plates" is enabled when the current frame has at least one box.
- When invoked, the feature iterates each targeted frame's boxes, reads the corresponding video frame, and runs a local image-analysis refinement routine over each box's ROI to produce a tighter fit to the plate.
- Refinement emits either a tighter axis-aligned rectangle OR, when rotation/shear is detected with sufficient confidence, an **oriented box** (rectangle with rotation angle). Oriented output is feature-flagged and falls back to AABB when the angle estimate is low-confidence.
- Extend the `PlateBox` data model to carry an optional rotation angle (°) — existing sidecar JSON continues to parse (angle defaults to 0.0).
- Blur export honours the rotation angle when rendering the blurred region (rotated rectangle mask instead of axis-aligned one).
- Overlay UI renders the rotated outline and lets the user reject a refinement per-frame (keep the pre-refine box) or for the whole clip.
- Progress dialog with per-frame status and cancel, running on a QThread worker.

## Capabilities

### New Capabilities
- `plate-box-refinement`: On-demand post-process that refines placed plate boxes to tighter (optionally oriented) boxes using image analysis of the ROI, gated on a "clip fully covered" precondition, with user accept/reject control.

### Modified Capabilities
- `plate-persistence`: Sidecar JSON gains an optional per-detection `angle` field; readers treat missing field as 0.0 (axis-aligned) for backward compatibility.
- `plate-blur-export`: Blur mask rendering accepts a rotation angle and produces a rotated-rectangle mask when angle ≠ 0.
- `plate-overlay-ui`: Overlay draws rotated-rectangle outlines and resize handles when a box carries a non-zero angle.

## Impact

- **Code**:
  - `src/trailvideocut/plate/models.py` — `PlateBox` gains optional `angle` field.
  - `src/trailvideocut/plate/` — new `refiner.py` module (ROI image analysis).
  - `src/trailvideocut/plate/storage.py` — serialise/deserialise `angle` with default.
  - `src/trailvideocut/plate/blur.py` (or equivalent) — rotated-rectangle blur mask.
  - `src/trailvideocut/ui/review_page.py` — new button, enablement logic, progress dialog.
  - `src/trailvideocut/ui/plate_overlay.py` — rotated-box drawing.
  - `src/trailvideocut/ui/workers.py` — new `PlateRefineWorker` QThread.
- **APIs**: New public methods on the plate service for "refine clip" and "refine frame". Signals for refinement progress / per-frame done / cancelled.
- **Dependencies**: Adds no new third-party libraries — refinement is built on the existing OpenCV + NumPy stack (adaptive thresholding, edge/contour analysis, `cv2.minAreaRect`).
- **Sidecar format**: `.plates.json` version bumped with an additive field; old files load unchanged.
- **Tests**: New unit tests for the refinement algorithm (synthetic and captured-frame fixtures), the angle-aware blur mask, the rotated overlay draw, and the enablement gate.
- **Performance**: Refinement runs off the UI thread; expected cost is a few ms per box; progress dialog + cancel make long clips tolerable.
