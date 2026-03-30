## Why

Plate detection results are currently stored only in memory (`ReviewPage._plate_data`). When the user closes the application or navigates away, all detected plates and manual edits are lost, forcing re-detection on every session. For videos with many clips this wastes significant time and GPU resources, and discards manual corrections the user has made to bounding boxes.

## What Changes

- Add a persistence layer that saves and loads `ClipPlateData` to/from a JSON file on disk, co-located with the video file (e.g., `<video>.plates.json`).
- Automatically load persisted plate data when opening a video that has a saved plate file.
- Save plate data after detection completes and whenever the user manually edits (add/move/resize/delete) a bounding box.
- Add UI controls to manage persisted data (clear saved plates, re-detect and overwrite).

## Capabilities

### New Capabilities
- `plate-persistence`: Serialize/deserialize `ClipPlateData` to JSON, auto-save on changes, auto-load on open.

### Modified Capabilities
- `plate-overlay-ui`: Add save indicator and "Clear Saved Plates" action to the review page UI.

## Impact

- **Code**: New `plate/storage.py` module; changes to `ui/review_page.py` to hook save/load into the workflow.
- **Data**: Creates `.plates.json` sidecar files next to video files.
- **Dependencies**: None (uses stdlib `json`).
