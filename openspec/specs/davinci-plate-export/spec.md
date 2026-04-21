## Purpose

The DaVinci plate-export capability extends the OTIO export pipeline so a Resolve project can apply per-plate Fusion blur to detected license plates. It embeds plate detections as OTIO clip metadata, generates a companion Python script that drives DaVinci Resolve's `DaVinciResolveScript` API to build Fusion blur compositions with keyframed rectangular masks, and — when running on WSL — auto-launches that script through a Windows-native Python interpreter so the user does not have to copy files between worlds. Frame alignment is preserved end-to-end so each Fusion keyframe lands on the same source frame as the on-screen preview overlay and the MP4 export.
## Requirements
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

### Requirement: Generate DaVinci Resolve automation script
When exporting to DaVinci Resolve with plate data, the system SHALL generate a Python script file (`.py`) alongside the `.otio` file. The script SHALL use DaVinci Resolve's `DaVinciResolveScript` API to:
1. Import the OTIO timeline into the current Resolve project
2. Iterate over clips with plate metadata
3. Add a Fusion composition to each clip containing Gaussian blur nodes with keyframed rectangular masks matching the plate bounding boxes

#### Scenario: Script generated alongside OTIO
- **WHEN** the user exports to DaVinci with plate data on at least one clip
- **THEN** the system SHALL write a `.py` file at the same path as the `.otio` file with suffix `_resolve_plates.py`

#### Scenario: No script when no plate data
- **WHEN** the user exports to DaVinci with no plate data on any clip
- **THEN** the system SHALL NOT generate a companion script (only the `.otio` file)

#### Scenario: Script applies blur per plate per frame
- **WHEN** a clip has 3 plates across 60 frames with varying positions
- **THEN** the generated script SHALL create 3 blur nodes in the Fusion composition, each with keyframed center/width/height matching the per-frame bounding box positions

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

### Requirement: Blur size auto-scaling by relative plate area
The Fusion Blur node's XBlurSize SHALL be auto-scaled based on the plate's bounding-box area (`w × h`) relative to all plates in the clip. The smallest plate area maps to XBlurSize=1.5, the largest to XBlurSize=2.5, with linear interpolation for intermediate sizes. All detected plates are included in the composition. Both code paths that emit XBlurSize keyframes — the offline Lua-script generator and the in-Resolve Python automation script — SHALL use this same range.

#### Scenario: Smallest plate in clip
- **WHEN** a plate has the smallest bounding-box area in the clip
- **THEN** the Fusion Blur node SHALL have XBlurSize=1.5

#### Scenario: Largest plate in clip
- **WHEN** a plate has the largest bounding-box area in the clip
- **THEN** the Fusion Blur node SHALL have XBlurSize=2.5

#### Scenario: All plates same size
- **WHEN** all plates in the clip have the same bounding-box area
- **THEN** all Fusion Blur nodes SHALL have XBlurSize=1.5

#### Scenario: Intermediate plate area
- **WHEN** a plate's bounding-box area lies exactly midway between the clip's smallest and largest plate areas
- **THEN** the Fusion Blur node SHALL have XBlurSize=2.0 (the midpoint of the [1.5, 2.5] range)

### Requirement: Export page UI controls for DaVinci plate export
The export page SHALL include a checkbox labeled "Include plate blur data" that is visible only when the DaVinci export mode is selected. The checkbox SHALL be enabled by default when plate data exists and `plate_blur_enabled` is True. The checkbox state SHALL control whether plate metadata is embedded in the OTIO and whether the companion script is generated.

#### Scenario: Checkbox visible in DaVinci mode with plates
- **WHEN** the user selects DaVinci export mode and plate data exists for at least one clip
- **THEN** the export page SHALL show an enabled "Include plate blur data" checkbox, checked by default

#### Scenario: Checkbox hidden in MP4 mode
- **WHEN** the user selects MP4 export mode
- **THEN** the "Include plate blur data" checkbox SHALL NOT be visible

#### Scenario: Checkbox disabled when no plates
- **WHEN** the user selects DaVinci export mode but no plate data exists
- **THEN** the checkbox SHALL be visible but disabled with a tooltip indicating no plate data is available

### Requirement: WSL path handling in generated script
The generated DaVinci Resolve script SHALL convert WSL filesystem paths (`/mnt/c/...`) to Windows-style paths (`C:\...`) for any file references, since DaVinci Resolve runs on the Windows host. This SHALL apply to the OTIO file path referenced within the script.

#### Scenario: WSL path in generated script
- **WHEN** the export runs on WSL and the OTIO file is at `/mnt/d/Videos/export.otio`
- **THEN** the generated script SHALL reference the file as `D:\Videos\export.otio`

#### Scenario: Non-WSL path unchanged
- **WHEN** the export runs on a native Linux or Windows system
- **THEN** the script SHALL use the native path format without conversion

### Requirement: Auto-apply blur via WSL interop
When the "Auto-apply in Resolve" option is enabled and the app runs on WSL, the system SHALL attempt to execute the companion script automatically by locating a Windows-native Python interpreter via WSL interop and invoking the script through it. The script runs as a native Windows process and connects to Resolve's DaVinciResolveScript IPC. The system SHALL target DaVinci Resolve Studio 20+ compatibility.

#### Scenario: Successful auto-apply with Resolve running
- **WHEN** the user exports with auto-apply enabled, Resolve Studio 20+ is running with external scripting enabled, and Windows Python is available via WSL interop
- **THEN** the system SHALL execute the companion script automatically, apply Fusion blur compositions, and report success

#### Scenario: Resolve not running — graceful fallback
- **WHEN** the user exports with auto-apply enabled but Resolve is not running
- **THEN** the system SHALL save the companion script alongside the OTIO file and display a message with the script path for manual execution

#### Scenario: Windows Python not found
- **WHEN** the user exports on WSL but no Windows Python interpreter can be found
- **THEN** the system SHALL save the companion script and inform the user to run it manually on Windows

#### Scenario: Not running on WSL
- **WHEN** the app runs on native Linux or Windows (not WSL)
- **THEN** the system SHALL save the companion script without attempting auto-execution via WSL interop

### Requirement: Auto-apply UI control
The export page SHALL include an "Auto-apply in Resolve" checkbox, visible only when DaVinci export mode is selected and "Include plate blur data" is checked. The checkbox SHALL control whether the system attempts WSL interop execution after generating the companion script.

#### Scenario: Auto-apply checkbox visible and checked by default
- **WHEN** the user selects DaVinci export mode and "Include plate blur data" is checked
- **THEN** the "Auto-apply in Resolve" checkbox SHALL be visible and checked by default

#### Scenario: Auto-apply disabled when plate export unchecked
- **WHEN** the user unchecks "Include plate blur data"
- **THEN** the "Auto-apply in Resolve" checkbox SHALL be disabled

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

