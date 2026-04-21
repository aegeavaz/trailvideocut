## MODIFIED Requirements

### Requirement: Map plate frame numbers to clip source ranges
The system SHALL translate plate detection frame numbers (absolute source-video frames) to frame offsets relative to each clip's source_range start time. This mapping SHALL account for the clip's source_start time and video frame rate so that plate coordinates align with the correct frame when the OTIO timeline is imported into Resolve. The window used for inclusion SHALL be the clip's effective window — `[source_start_frame, source_end_frame + tail_frames(clip_index, plan, fps))` — as defined by the `plate-clip-transition-tail` capability. Plates stored at source-frame keys inside that window SHALL be emitted in the clip's `metadata["trailvideocut"]["plates"]` with the frame offset `absolute_frame - source_start_frame`, which may exceed `(source_end_frame - source_start_frame) - 1` for tail-region plates. Plates outside the effective window SHALL be excluded.

#### Scenario: Plate at absolute frame 500 in a clip starting at frame 400
- **WHEN** a clip's source_start corresponds to frame 400 and a plate exists at absolute frame 500
- **THEN** the metadata SHALL store the plate at frame offset 100 (relative to clip start)

#### Scenario: Plate outside clip effective window is excluded
- **WHEN** a plate detection exists at frame 300 but the clip's effective window is frames 400–606 (core 400–600 plus a 6-frame tail)
- **THEN** that plate detection SHALL NOT appear in the clip's metadata

#### Scenario: Tail-region plate is included for a non-last crossfade clip
- **WHEN** a clip's core range is 400–600 with `tail_frames == 6` and a plate is stored at absolute frame 603
- **THEN** that plate SHALL appear in the clip's metadata at frame offset 203

#### Scenario: Tail-region plate is excluded on the last clip
- **WHEN** a plate is stored at an absolute frame past the last clip's `source_end_frame` (the last clip has `tail_frames == 0` by definition)
- **THEN** that plate SHALL NOT appear in the last clip's metadata

#### Scenario: Tail-region plate is excluded on a CUT plan
- **WHEN** a plate is stored at an absolute frame past a non-last clip's `source_end_frame` but the plan uses `CUT` transitions
- **THEN** that plate SHALL NOT appear in that clip's metadata because `tail_frames == 0`

### Requirement: Fusion comp-frame keyframes preserve source-frame alignment
The generated DaVinci Lua script SHALL map each plate detection at clip-relative source-frame index `rel` to a Fusion keyframe at comp frame `comp_for_rel(rel) = clip_offset + rel`, where `clip_offset = SRC_START_FRAME + MediaIn1.ClipTimeStart` (the latter compensating for Resolve's crossfade leading handle frames). No additive, subtractive, or piecewise-keyframe-conditional correction term SHALL be applied beyond `clip_offset`. Any future re-introduction of such a term requires concrete, documented evidence that Resolve's timeline-to-source mapping introduces that exact offset, and the condition must be recorded as a comment in the generator with the clip used to verify it. This mapping SHALL apply unchanged to tail-region plates: a plate at clip-relative source-frame index `rel` ≥ `(source_end_frame - source_start_frame)` SHALL still be emitted at `clip_offset + rel`, with no extra "tail" correction term.

#### Scenario: Keyframe for plate at clip-relative source frame K
- **WHEN** a plate detection exists at clip-relative source frame K for a clip placed at comp offset `clip_offset`
- **THEN** the Lua script SHALL set the mask Center/Width/Height keyframe at comp frame `clip_offset + K`, matching the same `boxes[K]` the preview overlay displays at that source frame and the same `boxes[K]` the MP4 export writes

#### Scenario: No spurious offset regardless of source-video origin
- **WHEN** a clip has plate detections at source frames K1 < K2 < K3 and the source video was either natively captured or concatenated from multiple source files
- **THEN** the Lua keyframes SHALL land at `clip_offset + K1`, `clip_offset + K2`, `clip_offset + K3` with no additional conditional offset, matching the MP4 export's pixel-level alignment at the same source frames

#### Scenario: Keyframe for a tail-region plate uses the same mapping
- **WHEN** clip 0 has core length 200 frames (`rel` = 0..199) and a tail-region plate at `rel == 203`
- **THEN** the Lua script SHALL set that plate's keyframe at comp frame `clip_offset + 203`, with no additive "tail offset" term beyond `clip_offset`

### Requirement: Fusion blur composition structure
The generated Fusion composition for each clip SHALL follow this node structure: MediaIn -> Merge(Background=MediaIn, Foreground=Blur) -> MediaOut. For each plate region, there SHALL be a separate Blur node with a Rectangle mask. The mask's center, width, height, and angle SHALL be keyframed per-frame using the plate bounding box data. The mask angle SHALL be converted from the PlateBox convention (degrees, applied in image-space with Y pointing down) to Fusion's `RectangleMask.Angle` convention (degrees, applied with Y pointing up) by negating the value, so the exported mask is visually congruent with the preview overlay. The Lua script SHALL insert zero-size boundary keyframes (Width=0, Height=0, Angle=0) at the frame immediately before the first detection and the frame immediately after the last detection for each plate track, preventing Fusion's spline hold behavior from extending blur to undetected frames. For clips with tail-region detections, the "last detection" used when placing the post-boundary keyframe SHALL be the last `rel` across both core and tail frames; the post-boundary keyframe SHALL land at `comp_for_rel(last_rel + 1)` and SHALL NOT be clamped to the core-range end.

#### Scenario: Single plate with constant position
- **WHEN** a clip has one plate at the same position across all frames with `angle == 0.0`
- **THEN** the Fusion composition SHALL have one Blur node with a Rectangle mask at a fixed position (no keyframes needed) and `RectangleMask.Angle == 0`

#### Scenario: Multiple plates with movement
- **WHEN** a clip has two plates, one moving and one stationary
- **THEN** the Fusion composition SHALL have two Blur nodes, each with its own Rectangle mask; the moving plate's mask SHALL have per-frame keyframes for center position

#### Scenario: Plate detection starts mid-clip in Fusion
- **WHEN** a clip has 300 frames and plate detections exist only for frames 100-250
- **THEN** the Lua script SHALL set a zero-size mask keyframe (Width=0, Height=0, Angle=0) at frame 99 (or comp_for_rel(99)) and a zero-size mask keyframe at frame 251 (or comp_for_rel(251)), so that Fusion does NOT display blur for frames 0-98 or frames 252-299

#### Scenario: Plate detection starts at frame 0
- **WHEN** a clip has plate detections starting from frame 0
- **THEN** the Lua script SHALL NOT insert a pre-boundary keyframe (since there are no preceding frames to suppress), and the first detection keyframe SHALL be set normally

#### Scenario: Plate detection ends at last frame
- **WHEN** a clip has plate detections ending at the last frame (frame_count - 1) of the effective window (core end + tail)
- **THEN** the Lua script SHALL NOT insert a post-boundary keyframe beyond the effective window, and the last detection keyframe SHALL be set normally

#### Scenario: Last detection sits inside the tail
- **WHEN** a clip with core length 200 and a 6-frame tail has plate detections at `rel` in {100, 150, 203}
- **THEN** the Lua post-boundary zero-size keyframe SHALL be placed at `comp_for_rel(204)` (one frame after the last tail detection), not at the core-range end

#### Scenario: Rotated plate mask is rotated in Fusion
- **WHEN** a plate track has detections with `angle == 30.0` at clip-relative frames K..K+N
- **THEN** the generated Lua SHALL include a `Angle = BezierSpline({})` assignment for that track's mask and per-frame keyframes `{mask_var}.Angle[comp_for_rel(frame)] = -30.0` for every densified frame in that range, reflecting the sign flip that converts the PlateBox Y-down convention to Fusion's Y-up convention

#### Scenario: In-Resolve Python path sets the same angle
- **WHEN** the in-Resolve Python automation script `apply_blur_to_clip()` processes a plate with `angle == 30.0` at frame F
- **THEN** it SHALL call `mask.SetInput("Angle", -30.0, F)` for that frame, matching the offline Lua generator's value exactly

#### Scenario: Axis-aligned plate does not visually rotate
- **WHEN** every detection in a track has `angle == 0.0`
- **THEN** every emitted `Angle` keyframe SHALL be `0.0` so the resulting mask is indistinguishable in orientation from the pre-rotation-support output
