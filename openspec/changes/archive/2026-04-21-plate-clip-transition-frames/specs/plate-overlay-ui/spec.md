## MODIFIED Requirements

### Requirement: Button state updates on navigation
The system SHALL update the enabled/disabled state of the action buttons (Detect Frame, Clear Clip Plates, Clear Frame Plates, Refine Clip Plates, Refine Frame Plates, Preview Blur) when the user navigates between clips or seeks to a different frame position, **and whenever the plate set of the current clip or frame changes through any overlay-driven edit** — including adding, moving, resizing, rotating, or deleting a plate box. Refresh of the enablement state SHALL NOT depend on the user leaving and re-entering the current frame; adding the very first plate on a clip or frame SHALL immediately activate the Refine Clip Plates, Refine Frame Plates, Clear Clip Plates, and Clear Frame Plates buttons. For the purposes of the "current frame belongs to the selected clip" check used by Clear Frame Plates, Refine Frame Plates, and Preview Blur, the clip's frame set SHALL be the effective window `clip_frame_window(selected_index, plan, fps)` defined by the `plate-clip-transition-tail` capability — i.e. it SHALL include the clip's transition tail when one applies.

#### Scenario: User navigates to clip with plate data
- **WHEN** the user selects a clip that has plate data
- **THEN** "Detect Frame" and "Clear Clip Plates" become enabled, and "Clear Frame Plates" is enabled only if the current frame has plates

#### Scenario: User seeks to frame without plates
- **WHEN** the user seeks to a frame with no detected plates (within a clip that has plate data)
- **THEN** "Clear Frame Plates" becomes disabled while "Detect Frame" and "Clear Clip Plates" remain enabled

#### Scenario: Adding the first plate to a clip enables refine buttons
- **WHEN** the selected clip has no plate detections anywhere, and the user adds a manual plate box on the current frame
- **THEN** "Refine Clip Plates" and "Refine Frame Plates" SHALL become enabled immediately (without requiring the user to change frames), along with "Clear Clip Plates" and "Clear Frame Plates"

#### Scenario: Adding a plate on a frame that previously had none
- **WHEN** the clip already has plates on other frames but the current frame has none, and the user adds a manual plate box on the current frame
- **THEN** "Refine Frame Plates" and "Clear Frame Plates" SHALL become enabled immediately

#### Scenario: Deleting the last plate on a frame
- **WHEN** the current frame has one plate and the user deletes it (via canvas or chip)
- **THEN** "Refine Frame Plates" and "Clear Frame Plates" SHALL become disabled immediately while "Refine Clip Plates" and "Clear Clip Plates" remain enabled as long as other frames in the clip still have plates

#### Scenario: Playhead in the selected clip's transition tail keeps frame-scoped buttons available
- **WHEN** the selected clip's tail is 6 frames and the playhead is at the 4th tail frame with a plate at that source-frame index in the clip's `detections`
- **THEN** "Clear Frame Plates" and "Refine Frame Plates" SHALL be enabled, and "Detect Frame" SHALL be enabled, exactly as if the playhead were inside the clip's core range

#### Scenario: Playhead past the tail falls through to the next clip
- **WHEN** the playhead is past the selected clip's effective window and inside the next clip's core range
- **THEN** the buttons SHALL reflect the next clip's plate state (not the selected clip's), the overlay SHALL bind to the next clip's data, and the timeline selection SHALL remain on the originally selected clip

### Requirement: Add a manual plate box
The system SHALL allow the user to add a new bounding box on the current frame. When two or more recent reference detections are available, the new box's position SHALL be computed by projecting the motion of those detections onto the current frame. When fewer than two reference detections are usable, the system SHALL fall back in order: clone the single nearest detection, then place at the mouse cursor position with a default size, then place at the frame center with a default size. In all three detection-aware paths (motion projection, nearest-reference clone, and — if the nearest reference is used to size a cursor/centre placement) the new box's `angle` SHALL be inherited from the nearest reference detection used, so that new manual boxes match the surrounding rotation instead of snapping back to axis-aligned. Only the pure default-size fallback used when no reference detection exists at all SHALL produce `angle == 0.0`. The new box SHALL always be marked `manual: true`, SHALL be clamped to remain fully within the frame (using the axis-aligned envelope of the rotated rectangle), and the system SHALL auto-save all plate data to the sidecar file. When the current frame lies in the selected clip's transition tail (as defined by the `plate-clip-transition-tail` capability), Add Plate SHALL still operate on the selected clip — the new box SHALL be stored under that clip's `ClipPlateData.detections[current_frame]` and projection SHALL consider that clip's full effective window (core range ∪ tail) when searching for reference detections.

#### Scenario: Projection with two prior detections
- **WHEN** the user triggers "Add plate box" at frame 60, frame 40 has a detected plate at normalized center (0.40, 0.50), and frame 50 has a detected plate at normalized center (0.45, 0.50)
- **THEN** a new box SHALL be created at frame 60 with its normalized center projected along the observed motion (approximately (0.50, 0.50)), using the size of the nearest reference detection, marked as `manual: true`

#### Scenario: Projection inherits rotation from the nearest reference
- **WHEN** the user triggers "Add plate box" at frame 60, prior detections at frame 40 and 50 both have `angle = 15°`, and the nearest reference (frame 50) is chosen for size
- **THEN** the new box SHALL have `angle = 15°`, inherited from the nearest reference

#### Scenario: Projection clamps to frame bounds
- **WHEN** a projected box's center would place its axis-aligned envelope partially outside the frame (e.g., the projected x is 0.98 with a width of 0.15)
- **THEN** the box SHALL be clamped so its envelope remains fully within the normalized range [0, 1] on both axes

#### Scenario: Projection between prior and next detections
- **WHEN** the user triggers "Add plate box" at frame 55, frame 50 has a detected plate, and frame 60 has a detected plate, and no other detections exist
- **THEN** a new box SHALL be created at frame 55 with its position interpolated along the motion between the two detections, marked as `manual: true`

#### Scenario: Projection with only next-side detections
- **WHEN** the user triggers "Add plate box" at frame 10, no frames before 10 have detections, and frames 20 and 30 have detected plates
- **THEN** a new box SHALL be created at frame 10 with its position extrapolated backward from those next-side detections, marked as `manual: true`

#### Scenario: Projection gap exceeds the motion window
- **WHEN** the only reference detections are more than the configured motion window (e.g., 60 frames) away from the current frame
- **THEN** the system SHALL NOT project; it SHALL fall back to cloning the nearest single reference detection (position, size, **and angle**), marked as `manual: true`

#### Scenario: Only one reference detection available inherits its rotation
- **WHEN** the user triggers "Add plate box" and only a single reference detection (with `angle = 12°`) is available in the clip
- **THEN** a new box SHALL be created at the current frame with the same position, size, and `angle = 12°` as that detection, marked as `manual: true`

#### Scenario: Add box with no detection in any frame, via right-click
- **WHEN** the user right-clicks on the video overlay to add a plate box and no frames in the current clip have any detections
- **THEN** a new box SHALL be created centered at the mouse cursor position with a default size (15% of frame width, 5% of frame height), `angle == 0.0`, marked as `manual: true`

#### Scenario: Add box with no detection in any frame, via button
- **WHEN** the user clicks the "Add Plate" button and no frames in the current clip have any detections
- **THEN** a new box SHALL be created at the center of the frame with a default size (15% of frame width, 5% of frame height), `angle == 0.0`, marked as `manual: true`

#### Scenario: Added box is immediately editable
- **WHEN** a manual box is added
- **THEN** the new box SHALL be automatically selected, ready for move/resize

#### Scenario: Add in the selected clip's transition tail uses a core-range reference
- **WHEN** clip 0's core range ends at frame 120 with a 6-frame tail, `detections[118]` holds a plate with `angle = 10°`, and the user clicks Add Plate at frame 123 (tail position 3/6)
- **THEN** a new box SHALL be cloned from the frame-118 reference, stored at clip 0's `detections[123]`, with `angle = 10°`, marked as `manual: true`
