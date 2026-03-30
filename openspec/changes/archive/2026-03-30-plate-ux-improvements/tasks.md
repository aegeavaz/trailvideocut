## 1. Cursor-Centered Zoom

- [x] 1.1 In `VideoPlayer.wheelEvent()`, capture the mouse position and scene point under cursor before applying zoom
- [x] 1.2 In `VideoPlayer._fit_video()`, accept an optional anchor scene point and viewport position; after `fitInView()` + `scale()`, adjust scroll bars so the anchor point maps back to the same viewport position
- [x] 1.3 Ensure zoom at min (1.0) and max (5.0) clamp correctly and do not shift the view
- [x] 1.4 Verify overlay synchronization: `zoom_changed` signal triggers `_update_overlay_effective_rect()` after scroll bar adjustment

## 2. Bidirectional Reference Box Search

- [x] 2.1 Rename `find_nearest_prior_box()` to `find_nearest_reference_box()` in `PlateOverlayWidget` and update all callers
- [x] 2.2 Extend search to look forward through frames when no prior frame has detections
- [x] 2.3 Add `get_last_mouse_norm_pos()` method to `PlateOverlayWidget` returning the last known mouse position in normalized coordinates (or None)

## 3. Mouse-Position Fallback for Add Plate

- [x] 3.1 Change `add_plate_requested` signal to carry normalized cursor position `(float, float)`
- [x] 3.2 Update `ReviewPage._on_add_plate()` to accept optional cursor position and use it as fallback when no reference box exists
- [x] 3.3 For the "Add Plate" button path (no mouse on video), query `PlateOverlayWidget.get_last_mouse_norm_pos()` or fall back to center

## 4. Tests

- [x] 4.1 Test `find_nearest_reference_box()` returns prior frame box when available
- [x] 4.2 Test `find_nearest_reference_box()` returns next frame box when no prior exists
- [x] 4.3 Test `find_nearest_reference_box()` returns None when no detections exist in any frame
