## ADDED Requirements

### Requirement: Embed plate data as OTIO clip metadata
When exporting to DaVinci Resolve with plate blur enabled, the system SHALL embed plate detection data in each OTIO clip's `metadata` dictionary under the key `trailvideocut.plates`. The metadata SHALL contain per-frame bounding boxes with coordinates mapped to source-video frame numbers relative to the clip's source range. Each plate entry SHALL include normalized coordinates (x, y, w, h).

#### Scenario: OTIO export with plate data for two clips
- **WHEN** the user exports to DaVinci with plate data on clips 0 and 2, and plate export is enabled
- **THEN** the OTIO file SHALL contain `metadata["trailvideocut"]["plates"]` on segments 1 and 3 (1-indexed) with per-frame bounding boxes, and segments without plate data SHALL have no plate metadata

#### Scenario: OTIO export with plate export disabled
- **WHEN** the user exports to DaVinci with plate data available but the plate export toggle is off
- **THEN** the OTIO file SHALL contain no plate metadata on any clip (identical to current behavior)

#### Scenario: Plate metadata coordinate format
- **WHEN** a clip has a plate detected at frame 150 with box (x=0.3, y=0.5, w=0.1, h=0.05)
- **THEN** the metadata for that clip SHALL contain frame key "150" mapping to a list with one entry: `{"x": 0.3, "y": 0.5, "w": 0.1, "h": 0.05}`

### Requirement: Map plate frame numbers to clip source ranges
The system SHALL translate plate detection frame numbers (absolute source-video frames) to frame offsets relative to each clip's source_range start time. This mapping SHALL account for the clip's source_start time and video frame rate so that plate coordinates align with the correct frame when the OTIO timeline is imported into Resolve.

#### Scenario: Plate at absolute frame 500 in a clip starting at frame 400
- **WHEN** a clip's source_start corresponds to frame 400 and a plate exists at absolute frame 500
- **THEN** the metadata SHALL store the plate at frame offset 100 (relative to clip start)

#### Scenario: Plate outside clip source range is excluded
- **WHEN** a plate detection exists at frame 300 but the clip's source range is frames 400-600
- **THEN** that plate detection SHALL NOT appear in the clip's metadata

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

### Requirement: Blur size auto-scaling by relative plate area
The Fusion Blur node's XBlurSize SHALL be auto-scaled based on the plate's bounding-box area (`w × h`) relative to all plates in the clip. The smallest plate area maps to XBlurSize=1.0, the largest to XBlurSize=2.0, with linear interpolation for intermediate sizes. All detected plates are included in the composition.

#### Scenario: Smallest plate in clip
- **WHEN** a plate has the smallest bounding-box area in the clip
- **THEN** the Fusion Blur node SHALL have XBlurSize=1.0

#### Scenario: Largest plate in clip
- **WHEN** a plate has the largest bounding-box area in the clip
- **THEN** the Fusion Blur node SHALL have XBlurSize=2.0

#### Scenario: All plates same size
- **WHEN** all plates in the clip have the same bounding-box area
- **THEN** all Fusion Blur nodes SHALL have XBlurSize=1.0

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
