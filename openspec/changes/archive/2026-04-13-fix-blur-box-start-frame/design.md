## Context

The blur export pipeline has two output paths:

1. **FFmpeg video export** (`PlateBlurProcessor` in `plate/blur.py`): Reads source frames via OpenCV, applies Gaussian blur to plate regions, and writes raw YUV to a temp file. Frame-to-box lookup uses `_get_boxes_for_frame()` which extrapolates to the nearest detection when a frame is outside the detection range (before first or after last detection). This was intended for crossfade-extended segments but causes every frame before the first detection to be blurred.

2. **DaVinci Resolve Fusion Lua script** (`resolve_script.py`): Generates Lua that creates RectangleMask + Blur nodes with BezierSpline/XYPath keyframes. Keyframes are only set at frames with detections (±2 nearest window). However, Fusion holds the first keyframe value for all preceding frames and the last keyframe value for all following frames, causing blur to appear from frame 0 through the end of the comp even when detections only span a subset.

Both bugs produce identical user-visible symptoms: blur appears from the beginning of a clip even when the plate only enters the frame mid-clip.

## Goals / Non-Goals

**Goals:**
- Blur SHALL only be applied to frames within (or ±2 frames of) the actual detection range
- Frames before the first detection and after the last detection SHALL have no blur
- Both export paths (FFmpeg and Lua) SHALL be fixed consistently

**Non-Goals:**
- Changing the ±2 frame nearest-window tolerance (it serves a valid purpose for dropped-frame resilience)
- Modifying the crossfade handle behavior (that's Resolve-side, not our concern)
- Changing the blur preview overlay behavior (it already works correctly since it renders per-frame)

## Decisions

### Decision 1: Remove extrapolation in `_get_boxes_for_frame()`

**Choice:** Remove the "outside detection range → nearest key" extrapolation branch entirely. When a frame is before `det_keys[0]` or after `det_keys[-1]`, return `[]`.

**Rationale:** The original intent was to handle crossfade-extended segments where Resolve adds a few handle frames outside the clip's source range. However, this extrapolation causes the entire prefix of the clip to be blurred when the plate doesn't appear until mid-clip. The `_nearest_boxes()` fallback (±2 window) already handles dropped-frame resilience within the detection range. For handle frames genuinely outside the range, no blur is the correct behavior — the plate is simply not visible there.

**Alternative considered:** Add a max-distance threshold (e.g., only extrapolate within 5 frames of the boundary). Rejected because it adds complexity and the extrapolation wasn't needed in practice — the ±2 nearest-window already covers the useful cases.

### Decision 2: Insert zero-size boundary keyframes in Lua script

**Choice:** For each plate track, insert a keyframe at `first_detection_frame - 1` (if ≥ 0) with mask Width=0 and Height=0 (center can be anything). Similarly, insert a keyframe at `last_detection_frame + 1` (if < frame_count) with Width=0 and Height=0.

**Rationale:** Fusion's BezierSpline holds the value of the first/last keyframe for all frames outside the keyframe range. By inserting a zero-size keyframe one frame before the first detection, the spline transitions from 0 (invisible) to the detection size in exactly one frame — a sharp cut. This is simple, reliable, and doesn't require changing Fusion's interpolation mode.

**Alternative considered:** Setting the spline's pre/post extrapolation mode to "constant" at zero. Rejected because Fusion's Lua API for controlling extrapolation modes is poorly documented and version-dependent. Zero-size keyframes are universally reliable.

## Risks / Trade-offs

- **[Risk] One-frame interpolation between zero-size and first detection keyframe:** Fusion's BezierSpline uses smooth interpolation by default, so the mask might briefly appear as a tiny dot at the transition frame. → **Mitigation:** The one frame of interpolation is imperceptible in playback (1/24s). If needed later, we can set the keyframe to "Linear" interpolation mode.

- **[Risk] Detection gap at frame 0:** If a plate is detected starting at frame 0, the boundary keyframe at frame -1 is clamped to frame 0, which could conflict with the actual detection keyframe. → **Mitigation:** Only insert the boundary keyframe when `first_detection_frame - 1 >= 0`. If the first detection is at frame 0, no boundary keyframe is needed since there are no preceding frames.
