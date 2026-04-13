## MODIFIED Requirements

### Requirement: Fusion blur composition structure
The generated Fusion composition for each clip SHALL follow this node structure: MediaIn -> Merge(Background=MediaIn, Foreground=Blur) -> MediaOut. For each plate region, there SHALL be a separate Blur node with a Rectangle mask. The mask's center, width, and height SHALL be keyframed per-frame using the plate bounding box data. The Lua script SHALL insert zero-size boundary keyframes (Width=0, Height=0) at the frame immediately before the first detection and the frame immediately after the last detection for each plate track, preventing Fusion's spline hold behavior from extending blur to undetected frames.

#### Scenario: Single plate with constant position
- **WHEN** a clip has one plate at the same position across all frames
- **THEN** the Fusion composition SHALL have one Blur node with a Rectangle mask at a fixed position (no keyframes needed)

#### Scenario: Multiple plates with movement
- **WHEN** a clip has two plates, one moving and one stationary
- **THEN** the Fusion composition SHALL have two Blur nodes, each with its own Rectangle mask; the moving plate's mask SHALL have per-frame keyframes for center position

#### Scenario: Plate detection starts mid-clip in Fusion
- **WHEN** a clip has 300 frames and plate detections exist only for frames 100-250
- **THEN** the Lua script SHALL set a zero-size mask keyframe (Width=0, Height=0) at frame 99 (or comp_for_rel(99)) and a zero-size mask keyframe at frame 251 (or comp_for_rel(251)), so that Fusion does NOT display blur for frames 0-98 or frames 252-299

#### Scenario: Plate detection starts at frame 0
- **WHEN** a clip has plate detections starting from frame 0
- **THEN** the Lua script SHALL NOT insert a pre-boundary keyframe (since there are no preceding frames to suppress), and the first detection keyframe SHALL be set normally

#### Scenario: Plate detection ends at last frame
- **WHEN** a clip has plate detections ending at the last frame (frame_count - 1)
- **THEN** the Lua script SHALL NOT insert a post-boundary keyframe (since there are no following frames to suppress), and the last detection keyframe SHALL be set normally
