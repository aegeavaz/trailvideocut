## Requirements

### Requirement: "Refine Clip Plates" action
The system SHALL provide a "Refine Clip Plates" action in the Review page's plate-action row that mirrors the enablement semantics of "Clear Clip Plates". The action SHALL be ENABLED if and only if a video is loaded, a clip is selected, and the selected clip has at least one plate box on at least one frame in its frame range; otherwise it SHALL be DISABLED. Full per-frame coverage SHALL NOT be a precondition. When invoked, the action SHALL target every `(frame_no, box)` pair present in the selected clip's detections and skip frames that have no boxes.

#### Scenario: Clip has at least one box
- **WHEN** the selected clip has one or more plate boxes on any frame in its range
- **THEN** "Refine Clip Plates" SHALL be enabled

#### Scenario: Clip has no boxes
- **WHEN** the selected clip has zero plate boxes across its entire frame range
- **THEN** "Refine Clip Plates" SHALL be disabled

#### Scenario: Frames without boxes are skipped, not blocking
- **WHEN** "Refine Clip Plates" is invoked on a clip where some frames have boxes and some frames have none
- **THEN** refinement SHALL run on the frames that have boxes and SHALL skip the others without error, and the button SHALL have been enabled regardless of the empty frames

#### Scenario: Enablement tracks detections
- **WHEN** the user deletes the last remaining plate box anywhere in the selected clip
- **THEN** "Refine Clip Plates" SHALL transition from enabled to disabled on the next repaint

### Requirement: "Refine Frame Plates" action
The system SHALL provide a "Refine Frame Plates" action in the Review page's plate-action row that mirrors the enablement semantics of "Clear Frame Plates". The action SHALL be ENABLED if and only if a video is loaded, a clip is selected, and the currently displayed frame has at least one plate box; otherwise it SHALL be DISABLED. When invoked, the action SHALL target only the boxes on the currently displayed frame.

#### Scenario: Current frame has a box
- **WHEN** the currently displayed frame has one or more plate boxes
- **THEN** "Refine Frame Plates" SHALL be enabled

#### Scenario: Current frame has no boxes
- **WHEN** the currently displayed frame has zero plate boxes
- **THEN** "Refine Frame Plates" SHALL be disabled

#### Scenario: Enablement tracks seek
- **WHEN** the user seeks from a frame with boxes to a frame with no boxes
- **THEN** "Refine Frame Plates" SHALL transition from enabled to disabled without any other user interaction

#### Scenario: Frame-scoped run does not touch other frames
- **WHEN** "Refine Frame Plates" is invoked on frame K in a clip that also has boxes on other frames
- **THEN** only boxes on frame K SHALL be passed to the refiner and only frame K's detections in `ClipPlateData` SHALL be eligible for modification (subject to user accept/revert); boxes on other frames SHALL remain unchanged

### Requirement: Post-process refinement pipeline
On invocation, the system SHALL iterate the target `(frame_no, box)` set (a whole clip's detections for "Refine Clip Plates"; a single frame's boxes for "Refine Frame Plates"). For each targeted box, the system SHALL decode the corresponding source-video frame and run a bounded-search image-analysis refinement over a padded ROI around the box. The refinement SHALL produce a `RefinementResult` containing: a candidate box (normalized coordinates and an optional rotation angle in degrees), a confidence score in `[0.0, 1.0]`, and a method tag drawn from `{"aabb", "oriented", "unchanged"}`. The algorithm SHALL NOT read or write any state outside the input frame and the input box; it is a pure function of those inputs.

#### Scenario: Tighter AABB on an axis-aligned plate
- **WHEN** the refinement runs against a synthetic frame containing a high-contrast axis-aligned plate rectangle that lies strictly inside the input box
- **THEN** the returned `RefinementResult.box` SHALL have `angle == 0.0` and SHALL be closer to the true plate bounds than the input box (IoU with ground truth strictly greater than IoU of the input box with ground truth), with `method == "aabb"`

#### Scenario: Oriented fit on a rotated plate
- **WHEN** the refinement runs against a synthetic frame containing a high-contrast plate rectangle rotated by 15° that lies strictly inside the input box
- **THEN** the returned `RefinementResult.box.angle` SHALL be within ±3° of 15° (or its symmetric equivalent in the OpenCV `minAreaRect` angle convention), with `method == "oriented"`

#### Scenario: Low-contrast input is left alone
- **WHEN** the refinement runs on an ROI where no contour survives the area, aspect-ratio, and centre filters
- **THEN** the returned `RefinementResult.method` SHALL be `"unchanged"`, `RefinementResult.box` SHALL equal the input box (including `angle == 0.0`), and `RefinementResult.confidence` SHALL be less than the configured low-confidence threshold

### Requirement: Off-thread execution with progress and cancellation
Refinement SHALL run on a background QThread worker (`PlateRefineWorker`). The worker SHALL emit a `progress(done, total)` signal at least once per frame, a `frame_done(frame_no, before_box, after_box, confidence, method)` signal per processed box, a terminal `finished(results)` signal on success, and a terminal `cancelled()` signal if cancellation was requested. The Review page SHALL display a modal progress dialog with a Cancel button that invokes cancellation.

#### Scenario: Cancel mid-run
- **WHEN** the user clicks Cancel while the worker is iterating frames
- **THEN** the worker SHALL stop iterating at the next frame boundary, emit `cancelled()`, and the Review page SHALL make no changes to `ClipPlateData` and SHALL NOT call `save_plates()`

#### Scenario: UI remains responsive
- **WHEN** refinement is running on a long clip
- **THEN** the UI event loop SHALL continue to process events (progress dialog can redraw, Cancel button remains clickable), and the Qt signals from the worker SHALL be delivered via a queued connection

### Requirement: User review of refinements before persistence
On worker completion, the system SHALL present a "Review Refinements" dialog listing every refined frame with a before/after preview (rendered on a decoded thumbnail). The user SHALL be able to accept or revert each frame's refinement individually, accept all refinements whose confidence is at or above the configured high-confidence threshold, or revert everything. Only accepted refinements SHALL be written back to `ClipPlateData` and persisted via the existing `save_plates` path. If the user closes the dialog with Cancel, no refinements SHALL be applied.

#### Scenario: Accept all high-confidence
- **WHEN** the user clicks "Accept all high-confidence"
- **THEN** every per-frame entry whose `confidence >= HIGH_CONFIDENCE_THRESHOLD` SHALL be marked accepted and every other entry SHALL remain in its current state (default: reverted), and the dialog SHALL indicate the selection visually

#### Scenario: Apply accepted refinements
- **WHEN** the user clicks OK with at least one accepted refinement
- **THEN** the accepted refined boxes SHALL replace the original boxes at their frame indices in `ClipPlateData.detections`, and `save_plates(video_path, plate_data)` SHALL be invoked exactly once for the current video

#### Scenario: Cancel the review dialog
- **WHEN** the user clicks Cancel on the review dialog after the worker completes
- **THEN** `ClipPlateData.detections` SHALL be unchanged and `save_plates` SHALL NOT be invoked as a result of the refinement flow

### Requirement: Refinement preserves per-box metadata
A refined box SHALL preserve the source box's `manual` flag and SHALL set its `confidence` to the box's original `confidence` (detection confidence), NOT to the refinement algorithm's internal confidence score. The refinement-algorithm confidence SHALL be propagated to the review dialog for user-visible ranking only.

#### Scenario: Manual box stays manual after refinement
- **WHEN** a box that was previously marked `manual: true` is accepted from the review dialog with a refined geometry
- **THEN** the box written back to `ClipPlateData` SHALL still have `manual == True`

#### Scenario: Detection confidence preserved
- **WHEN** a detected box has `confidence == 0.82` and is accepted from the review dialog with a refined geometry
- **THEN** the box written back SHALL still have `confidence == 0.82`

### Requirement: Oriented output is opt-in per refinement
The refinement SHALL return an oriented rectangle (`angle != 0`) only when the absolute rotation is at least a minimum threshold (default 2°) and the oriented candidate's score exceeds the best axis-aligned candidate's score by a non-zero margin. Otherwise the refinement SHALL return an axis-aligned rectangle (`angle == 0.0`).

#### Scenario: Barely rotated plate stays axis-aligned
- **WHEN** the best rotated candidate has `|angle| < 2°`
- **THEN** `RefinementResult.box.angle` SHALL equal `0.0` and `method` SHALL equal `"aabb"`

#### Scenario: Significant rotation produces oriented output
- **WHEN** the best rotated candidate has `|angle| == 10°` and outscores the best AABB candidate by a positive margin
- **THEN** `RefinementResult.box.angle` SHALL equal the rotated candidate's angle and `method` SHALL equal `"oriented"`

### Requirement: Refinement is a pure, deterministic function of its inputs
Given identical `(frame_pixels, input_box, configuration)`, the refinement SHALL return an identical `RefinementResult` across runs. The refiner SHALL NOT depend on wall-clock time, random state that is not explicitly seeded from the inputs, or any mutable global state.

#### Scenario: Repeated call determinism
- **WHEN** `refine_box(frame, box, cfg)` is invoked twice with identical arguments in the same process
- **THEN** the two returned `RefinementResult` objects SHALL be equal field-by-field (box components, angle, confidence, method)
