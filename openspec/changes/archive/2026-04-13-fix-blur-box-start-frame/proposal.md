## Why

Blur boxes are applied from the very beginning of a clip even when plate detections only start mid-clip. This produces visible blur on clean frames where no license plate exists, degrading video quality. The bug affects both the FFmpeg video export path and the DaVinci Resolve Fusion Lua script export.

## What Changes

- **Fix Lua script keyframe boundaries**: Insert zero-size mask keyframes at the frame immediately before the first detection (and after the last detection) for each plate track. This prevents Fusion's BezierSpline/XYPath from holding the first keyframe value across all preceding frames.
- **Fix FFmpeg export extrapolation**: Change `PlateBlurProcessor._get_boxes_for_frame()` to stop extrapolating blur boxes to frames outside the detection range. Frames before the first detection or after the last detection should return no boxes (empty list), not the nearest detection's boxes.

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `plate-blur-export`: Blur SHALL only be applied to frames within the detection range, not extrapolated to the entire clip duration.
- `davinci-plate-export`: Fusion Lua scripts SHALL insert boundary keyframes that disable the blur mask outside the detection range, preventing Fusion's spline hold behavior from extending blur to undetected frames.

## Impact

- `src/trailvideocut/plate/blur.py` — `PlateBlurProcessor._get_boxes_for_frame()`: remove extrapolation outside detection range
- `src/trailvideocut/editor/resolve_script.py` — `_generate_lua_script_for_clip()`: add zero-size boundary keyframes before first and after last detection per track
- Existing tests for blur export and Lua script generation need updates to verify boundary behavior
