## Why

Trail camera videos often capture license plates that need to be detected and tracked for privacy blurring or identification purposes. Currently, the app has no plate detection capability, requiring users to manually identify and annotate plates frame-by-frame in external tools. Adding automated plate detection directly in the UI, with manual correction support, streamlines this workflow significantly.

## What Changes

- Add a new plate detection backend module using OpenCV/YOLO-based detection to locate license plates in video frames
- Add a "Detect Plates" button on the Review page that runs detection on selected clip(s) or all clips
- Run plate detection as a background worker thread (like existing AnalysisWorker) with progress reporting
- Overlay detected plate bounding boxes on the video player during playback
- Allow users to select, move, resize, and delete detected plate boxes to correct false positives or misplacements
- Allow users to manually add a plate box on any frame, pre-populated from the last detected plate's position/size
- Store plate detection results per-clip as a list of frame-level bounding boxes
- UI-only feature: no changes to the CLI interface

## Capabilities

### New Capabilities
- `plate-detector`: Backend detection engine that processes video frames and returns bounding box coordinates for detected license plates
- `plate-overlay-ui`: Video player overlay system for rendering, selecting, moving, resizing, and manually adding plate bounding boxes on the video display
- `plate-detection-workflow`: UI workflow integration: "Detect Plates" button, background worker, progress feedback, and detection data management on the Review page

### Modified Capabilities

_None_ - this is a purely additive feature with no changes to existing capabilities.

## Impact

- **New dependency**: A plate detection model/library (e.g., `ultralytics` for YOLOv8, or OpenCV DNN with a pre-trained plate detection model)
- **Affected code**: `src/trailvideocut/ui/review_page.py` (new button + workflow), `src/trailvideocut/ui/video_player.py` (overlay rendering), `src/trailvideocut/ui/workers.py` (new PlateDetectionWorker)
- **New modules**: `src/trailvideocut/plate/` directory for detection backend, `src/trailvideocut/ui/plate_overlay.py` for the interactive overlay widget
- **Data model**: New `PlateDetection` dataclass with per-frame bounding boxes, stored alongside clip data
- **No CLI changes**: Feature is exclusively available in the PySide6 UI
