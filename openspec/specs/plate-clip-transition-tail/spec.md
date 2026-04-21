# plate-clip-transition-tail Specification

## Purpose
TBD - created by archiving change plate-clip-transition-frames. Update Purpose after archive.
## Requirements
### Requirement: Derive per-clip transition-tail frame count from the cut plan

The system SHALL expose a pure helper `tail_frames(clip_index, plan, fps) -> int` that returns the number of source-video frames in a clip's transition tail. The helper SHALL return `round(plan.crossfade_duration * fps)` when both of these hold:

1. `plan.transition_style == TransitionStyle.CROSSFADE.value`, and
2. `clip_index < len(plan.decisions) - 1` (i.e. the clip is not the last one).

Otherwise the helper SHALL return `0`. The helper SHALL live in `src/trailvideocut/editor/models.py` (or a dedicated module reachable from both the UI and the exporter) so that the Review page, the exporter, the overlay, and the projection code share a single source of truth.

#### Scenario: Crossfade clip that is not the last one
- **WHEN** `plan.transition_style == "CROSSFADE"`, `plan.crossfade_duration == 0.2`, `fps == 30`, and `clip_index == 0` in a 3-decision plan
- **THEN** `tail_frames(0, plan, 30)` SHALL equal `6`

#### Scenario: Last clip in a crossfade plan
- **WHEN** `clip_index == len(plan.decisions) - 1` on a crossfade plan
- **THEN** `tail_frames(...)` SHALL equal `0`

#### Scenario: Cut-style plan
- **WHEN** `plan.transition_style == "CUT"` regardless of `crossfade_duration`
- **THEN** `tail_frames(...)` SHALL equal `0` for every clip

#### Scenario: Non-integer frame count is rounded
- **WHEN** `plan.crossfade_duration == 0.2` and `fps == 29.97`
- **THEN** `tail_frames(...)` SHALL equal `round(0.2 * 29.97) == 6`

### Requirement: Effective clip frame window

The system SHALL expose a helper `clip_frame_window(clip_index, plan, fps) -> tuple[int, int]` returning `(start_frame, end_frame_exclusive)` for clip `clip_index`, where:

- `start_frame == position_to_frame(plan.decisions[clip_index].source_start, fps)` (unchanged from today's core range), and
- `end_frame_exclusive == position_to_frame(plan.decisions[clip_index].source_end, fps) + tail_frames(clip_index, plan, fps)`.

Every plate-management gate — button enablement, overlay sync, export filtering, projection — SHALL compute the clip's frame membership via this helper rather than re-deriving it.

#### Scenario: Crossfade non-last clip window includes the tail
- **WHEN** clip 0's `source_end_frame == 120`, `tail_frames(0, plan, fps) == 6`
- **THEN** `clip_frame_window(0, plan, fps)` SHALL return `(source_start_frame, 126)` (126 is exclusive)

#### Scenario: Last clip window is the core range
- **WHEN** clip is the last decision in the plan
- **THEN** `clip_frame_window(...)` SHALL return the exact `[source_start_frame, source_end_frame)` with no tail extension

### Requirement: Plate actions recognise tail frames as part of the selected clip

On the Review page, when the user has selected clip N and the current frame `F` satisfies `start_frame <= F < end_frame_exclusive` as returned by `clip_frame_window(N, plan, fps)`, the system SHALL treat `F` as a frame of clip N for all plate-management purposes. This applies to the plate overlay's active clip data binding, the Detect Frame / Add Plate / Clear Frame Plates / Refine Frame Plates / Preview Blur buttons, the Delete/Backspace keyboard shortcut, and right-click "Add plate box". The selected clip index SHALL NOT change when the playhead enters or leaves the tail.

#### Scenario: Playhead enters the tail of the selected clip
- **WHEN** the user has clip 0 selected, clip 0 ends at source-frame 120, its tail is 6 frames, and the user seeks to source-frame 123
- **THEN** the overlay SHALL keep showing clip 0's plate data, `Detect Frame` / `Add Plate` SHALL remain enabled (subject to the "not currently detecting" rule), and right-click `Add plate box` on the overlay SHALL create the manual box on clip 0's `ClipPlateData.detections[123]`

#### Scenario: Playhead is in the tail and the frame has a plate
- **WHEN** a plate is stored at `detections[123]` of clip 0 and the playhead is at frame 123
- **THEN** `Clear Frame Plates` and `Refine Frame Plates` SHALL be enabled, `Clear Frame Plates` SHALL delete that entry, and `Refine Frame Plates` SHALL refine it

#### Scenario: Playhead past the tail
- **WHEN** the playhead is past `end_frame_exclusive` of the selected clip and inside the next clip's core range
- **THEN** the overlay SHALL fall back to the existing "first clip whose window contains the frame" rule (the next clip), and button enablement SHALL reflect that clip's state — but the selected clip SHALL remain unchanged in the timeline

### Requirement: Manual plate projection handles the tail boundary

The manual-plate projection logic SHALL accept reference detections drawn from the full `clip_frame_window(...)` of the owning clip. When the target frame lies in the tail region and a reference detection exists inside the core range (or vice-versa), projection SHALL proceed normally (motion projection when two references exist, nearest-clone fallback when only one exists). The projected plate SHALL be stored under the owning clip's `ClipPlateData.detections[target_frame]` at its absolute source-video frame key.

#### Scenario: Add plate at tail frame with nearby core reference
- **WHEN** clip 0 core ends at frame 120, tail extends to frame 126, `detections[118]` holds a plate, and the user clicks Add Plate at frame 123
- **THEN** a manual box SHALL be cloned from the frame-118 reference (inheriting its angle) and stored at `detections[123]` of clip 0

#### Scenario: Add plate at core frame with only a tail reference
- **WHEN** clip 0's only existing detection is at frame 124 (inside the tail) and the user clicks Add Plate at frame 119 (inside the core)
- **THEN** a manual box SHALL be cloned from the frame-124 reference, stored at `detections[119]` of clip 0, and its `angle` SHALL equal the reference's `angle`

### Requirement: Timeline shows the transition tail

The Review page timeline SHALL render every non-last CROSSFADE clip's tail as a visually distinct band attached to the right edge of that clip. The band SHALL be visibly distinct from the clip body and from the next clip, use a consistent colour, and never exceed the width represented by `tail_frames(...)` frames at the timeline's pixel-per-second scale. For CUT timelines, no tail band SHALL be drawn.

#### Scenario: Tail rendered for a crossfade clip
- **WHEN** the Review page is displayed with a 3-clip CROSSFADE plan and clip 1 has `tail_frames == 6`
- **THEN** clip 1's timeline rectangle SHALL have a narrower right-edge sub-band whose width equals the equivalent of 6 frames at the current horizontal scale, rendered in a colour distinct from the clip body

#### Scenario: Cut plan shows no tail band
- **WHEN** the user switches the timeline's transition style to CUT on the Export page and re-enters Review
- **THEN** no tail sub-band SHALL be drawn on any clip

### Requirement: Transition-tail badge in the Review page

When the currently selected clip has `tail_frames(...) > 0`, the Review page SHALL display the tail frame count alongside the clip's range read-out, in the form `<hh:mm:ss.mmm> - <hh:mm:ss.mmm> + N tail frames` (or equivalent labelled text). When the playhead is inside the tail, the badge or a co-located tooltip SHALL also report the frame's position within the tail, e.g. `tail 3/6`.

#### Scenario: Badge on a crossfade clip
- **WHEN** the selected clip's tail is 6 frames at 30 fps
- **THEN** the read-out SHALL show `... + 6 tail frames`

#### Scenario: In-tail indicator
- **WHEN** the playhead is on the 3rd tail frame of a 6-frame tail
- **THEN** a co-located label or tooltip SHALL show `tail 3/6`

#### Scenario: No badge on last clip or CUT plan
- **WHEN** the selected clip has `tail_frames == 0` (it is the last clip or the plan is CUT)
- **THEN** no tail-frame badge SHALL be shown

### Requirement: Stored tail plates are not silently truncated

When `ClipPlateData.detections` contains entries for frames outside the current `clip_frame_window(...)` (e.g. because `plan.crossfade_duration` was reduced after the plates were added), the Review page SHALL indicate this via a warning affordance on the clip (e.g. badge colour change or tooltip) so the user can correct or remove the now-orphaned plates. The system SHALL NOT silently drop those entries from memory or persisted storage.

#### Scenario: Orphan tail plates after shortening the crossfade
- **WHEN** a plate was stored at `detections[124]` when `tail_frames == 6`, and the user later shortens the crossfade so `tail_frames == 3` (new window exclusive end is 123)
- **THEN** the stored plate SHALL remain in memory and on disk, and the Review page SHALL surface a visual warning on clip 0 indicating one plate lies outside the effective window

