## MODIFIED Requirements

### Requirement: Embed plate data as OTIO clip metadata
When exporting to DaVinci Resolve with plate blur enabled, the system SHALL embed plate detection data in each OTIO clip's `metadata` dictionary under the key `trailvideocut.plates`. The metadata SHALL contain per-frame bounding boxes with coordinates mapped to source-video frame numbers relative to the clip's source range. Each plate entry SHALL include normalized coordinates (x, y, w, h) and the rotation angle in degrees (`angle`, float). Consumers SHALL default a missing `angle` key to `0.0` so OTIO files written before this capability gained rotation support remain readable.

#### Scenario: OTIO export with plate data for two clips
- **WHEN** the user exports to DaVinci with plate data on clips 0 and 2, and plate export is enabled
- **THEN** the OTIO file SHALL contain `metadata["trailvideocut"]["plates"]` on segments 1 and 3 (1-indexed) with per-frame bounding boxes, and segments without plate data SHALL have no plate metadata

#### Scenario: OTIO export with plate export disabled
- **WHEN** the user exports to DaVinci with plate data available but the plate export toggle is off
- **THEN** the OTIO file SHALL contain no plate metadata on any clip (identical to current behavior)

#### Scenario: Plate metadata coordinate format
- **WHEN** a clip has a plate detected at frame 150 with box (x=0.3, y=0.5, w=0.1, h=0.05, angle=0.0)
- **THEN** the metadata for that clip SHALL contain frame key "150" mapping to a list with one entry: `{"x": 0.3, "y": 0.5, "w": 0.1, "h": 0.05, "angle": 0.0}`

#### Scenario: Plate metadata carries rotation angle
- **WHEN** a clip has a plate detected at frame 150 with box (x=0.3, y=0.5, w=0.1, h=0.05, angle=22.5)
- **THEN** the metadata for that clip SHALL contain frame key "150" mapping to a list with one entry whose `angle` field equals `22.5` (within floating-point tolerance)

#### Scenario: Legacy OTIO without angle field
- **WHEN** the generator reads a plate dict that lacks an `angle` key (e.g. loaded from an OTIO file written before this change)
- **THEN** it SHALL behave as though `angle == 0.0` and produce an axis-aligned Fusion mask for that plate

### Requirement: Fusion blur composition structure
The generated Fusion composition for each clip SHALL follow this node structure: MediaIn -> Merge(Background=MediaIn, Foreground=Blur) -> MediaOut. For each plate region, there SHALL be a separate Blur node with a Rectangle mask. The mask's center, width, height, and angle SHALL be keyframed per-frame using the plate bounding box data. The mask angle SHALL be converted from the PlateBox convention (degrees, applied in image-space with Y pointing down) to Fusion's `RectangleMask.Angle` convention (degrees, applied with Y pointing up) by negating the value, so the exported mask is visually congruent with the preview overlay. The Lua script SHALL insert zero-size boundary keyframes (Width=0, Height=0, Angle=0) at the frame immediately before the first detection and the frame immediately after the last detection for each plate track, preventing Fusion's spline hold behavior from extending blur to undetected frames.

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
- **WHEN** a clip has plate detections ending at the last frame (frame_count - 1)
- **THEN** the Lua script SHALL NOT insert a post-boundary keyframe (since there are no following frames to suppress), and the last detection keyframe SHALL be set normally

#### Scenario: Rotated plate mask is rotated in Fusion
- **WHEN** a plate track has detections with `angle == 30.0` at clip-relative frames K..K+N
- **THEN** the generated Lua SHALL include a `Angle = BezierSpline({})` assignment for that track's mask and per-frame keyframes `{mask_var}.Angle[comp_for_rel(frame)] = -30.0` for every densified frame in that range, reflecting the sign flip that converts the PlateBox Y-down convention to Fusion's Y-up convention

#### Scenario: In-Resolve Python path sets the same angle
- **WHEN** the in-Resolve Python automation script `apply_blur_to_clip()` processes a plate with `angle == 30.0` at frame F
- **THEN** it SHALL call `mask.SetInput("Angle", -30.0, F)` for that frame, matching the offline Lua generator's value exactly

#### Scenario: Axis-aligned plate does not visually rotate
- **WHEN** every detection in a track has `angle == 0.0`
- **THEN** every emitted `Angle` keyframe SHALL be `0.0` so the resulting mask is indistinguishable in orientation from the pre-rotation-support output
