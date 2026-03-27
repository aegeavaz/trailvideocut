## Why

Debugging and improving plate detection accuracy requires inspecting what the model sees frame-by-frame — confidence values, box positions, and the actual video frame with the detection overlay. Currently this is only possible through the UI, which doesn't provide raw detection data. A CLI debug command enables rapid iteration on detection quality without the UI overhead.

## What Changes

- Add a new `detect-plates` CLI command via Typer that runs plate detection on a video file (or a time range within it)
- For each processed frame, save a screenshot with the detection bounding box drawn on it to an output folder
- Generate a detailed CSV/log file with per-frame detection data: frame number, timestamp, box coordinates (normalized and pixel), confidence, and box dimensions
- Support configurable confidence threshold to experiment with sensitivity
- Support optional time range (`--start`, `--end`) to focus on a specific clip

## Capabilities

### New Capabilities
- `plate-detect-cli`: CLI command for running plate detection on a video with debug output (annotated frame screenshots + detection log file)

### Modified Capabilities

_None_

## Impact

- **New code**: `src/trailvideocut/cli.py` — new `detect-plates` command
- **Reuses**: `src/trailvideocut/plate/detector.py` (PlateDetector), `src/trailvideocut/plate/model_manager.py` (model download)
- **New dependency**: None (uses existing OpenCV for drawing + csv stdlib)
- **Output artifacts**: folder with annotated PNG frames + `detections.csv` log file
