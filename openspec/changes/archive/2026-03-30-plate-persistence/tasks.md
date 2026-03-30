## 1. Storage Module

- [x] 1.1 Create `src/trailvideocut/plate/storage.py` with `save_plates(video_path, plate_data)` and `load_plates(video_path)` functions
- [x] 1.2 Implement JSON serialization of `dict[int, ClipPlateData]` with version field and video filename
- [x] 1.3 Implement JSON deserialization back to `dict[int, ClipPlateData]` with validation (corrupt file, unknown version)
- [x] 1.4 Add sidecar path helper: `get_plates_path(video_path) -> Path` returning `<stem>.plates.json`

## 2. Auto-Load on Open

- [x] 2.1 In `ReviewPage.set_cut_plan()`, call `load_plates()` and populate `_plate_data` if sidecar exists
- [x] 2.2 Validate loaded clip indices against current `CutPlan.decisions`, discard mismatched entries
- [x] 2.3 Update overlay and clip list to reflect loaded plate data
- [x] 2.4 Show status message when plates are loaded from disk

## 3. Auto-Save on Changes

- [x] 3.1 Call `save_plates()` after `PlateDetectionWorker.finished` delivers results
- [x] 3.2 Call `save_plates()` after manual box edits (add/move/resize/delete) in `PlateOverlayWidget`
- [x] 3.3 Handle `PermissionError` on save — show warning, continue without persistence

## 4. UI Controls

- [x] 4.1 Add "Clear Saved Plates" button to plate controls area, enabled only when plate data exists
- [x] 4.2 Implement clear action: delete sidecar file, clear `_plate_data`, hide overlay, update status
- [x] 4.3 Add status label showing "Plates loaded from disk" when data was loaded from sidecar

## 5. Tests

- [x] 5.1 Test round-trip serialization: save then load produces identical `ClipPlateData`
- [x] 5.2 Test loading with mismatched clip indices discards invalid entries
- [x] 5.3 Test loading corrupt/invalid JSON returns empty data with no crash
- [x] 5.4 Test `get_plates_path()` produces correct sidecar filename
