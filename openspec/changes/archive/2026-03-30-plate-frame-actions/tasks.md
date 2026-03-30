## 1. UI Buttons & Layout

- [x] 1.1 Add second button row in `review_page.py` with "Detect Frame", "Clear Clip Plates", and "Clear Frame Plates" buttons (disabled by default)
- [x] 1.2 Wire button click signals to handler stubs (`_on_detect_frame`, `_on_clear_clip_plates`, `_on_clear_frame_plates`)

## 2. Single-Frame Detection

- [x] 2.1 Implement `_on_detect_frame` handler: model check, frame extraction via OpenCV, run `detect_frame_tiled()`, merge results preserving manual boxes, save, refresh overlay
- [x] 2.2 Add lazy `PlateDetector` caching on `ReviewPage` — initialize on first use, recreate when settings change
- [x] 2.3 Handle model-not-downloaded case: trigger download flow, then run single-frame detection on completion

## 3. Clear Clip Plates

- [x] 3.1 Implement `_on_clear_clip_plates` handler: confirmation dialog, remove clip from `_plate_data`, persist, refresh overlay and plate list
- [x] 3.2 Handle edge case: if no plate data remains after clearing, delete sidecar file and disable plate UI controls

## 4. Clear Frame Plates

- [x] 4.1 Implement `_on_clear_frame_plates` handler: remove frame key from `ClipPlateData.detections`, persist, refresh overlay and plate list

## 5. Button State Management

- [x] 5.1 Update `_on_plate_finished` to enable/disable new buttons based on current state
- [x] 5.2 Update `_sync_overlay_to_current_clip` and `_update_plate_overlay_frame` to refresh new button enabled states on clip/frame navigation
- [x] 5.3 Disable new buttons during clip-level detection (in `_start_plate_detection`) and re-enable on completion/error

## 6. Tests

- [x] 6.1 Write unit tests for single-frame detection merge logic (auto replaced, manual preserved)
- [x] 6.2 Write unit tests for clear clip plates (removes clip data, handles last-clip edge case)
- [x] 6.3 Write unit tests for clear frame plates (removes frame entry, no-op when empty)
- [x] 6.4 Write unit tests for button state management (enabled/disabled transitions)

## 7. Delete Key Fallback

- [x] 7.1 Add `_on_delete_key` dispatch method: delete selected plate if one is selected, otherwise clear frame plates
- [x] 7.2 Rewire Del/Backspace QShortcuts to `_on_delete_key`
- [x] 7.3 Update specs with keyboard shortcut scenarios
