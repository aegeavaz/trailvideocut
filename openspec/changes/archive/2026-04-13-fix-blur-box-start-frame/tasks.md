## 1. Fix FFmpeg Export Path (PlateBlurProcessor)

- [x] 1.1 Remove the extrapolation branch in `PlateBlurProcessor._get_boxes_for_frame()` (`plate/blur.py:436-448`): when `frame_num < det_keys[0]` or `frame_num > det_keys[-1]`, return `[]` instead of extrapolating to the nearest detection key
- [x] 1.2 Write unit test for `_get_boxes_for_frame()` verifying that frames outside the detection range return an empty list
- [x] 1.3 Write unit test for `_get_boxes_for_frame()` verifying that frames inside the detection range with no entry still return `[]` (existing behavior preserved)

## 2. Fix DaVinci Resolve Lua Script Path

- [x] 2.1 In `_generate_lua_script_for_clip()` (`resolve_script.py`), after building `kf_data` for each track, compute `first_kf_frame` and `last_kf_frame` from the keyframe list
- [x] 2.2 Insert a zero-size boundary keyframe (Width=0, Height=0) at `first_kf_frame - 1` if `first_kf_frame > 0`, for Center, Width, Height, and XBlurSize splines
- [x] 2.3 Insert a zero-size boundary keyframe at `last_kf_frame + 1` if `last_kf_frame + 1 < frame_count`, for Center, Width, Height, and XBlurSize splines
- [x] 2.4 Write unit test verifying that the generated Lua script contains zero-size boundary keyframes when detections start mid-clip
- [x] 2.5 Write unit test verifying that no boundary keyframe is inserted when detections start at frame 0 or end at the last frame

## 3. Integration Verification

- [x] 3.1 Run existing test suite to ensure no regressions
- [x] 3.2 Verify that `_compute_blur_sizes()` still works correctly with the boundary frames (it should skip zero-size entries or not be affected since boundary frames have no box in `_nearest_box_for_frame`)
