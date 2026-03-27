## ADDED Requirements

### Requirement: Tiled detection for small plates
The system SHALL support a tiled detection mode that splits each frame into overlapping 320x320 crops, upscales each to 640x640, runs detection, and maps coordinates back to the original frame. This SHALL be the default detection mode.

#### Scenario: Tiled detection finds small plate
- **WHEN** a frame contains a plate that is 20-40px wide
- **THEN** the tiled detector SHALL detect it with confidence > 0.2 by magnifying the region 2x

#### Scenario: NMS merges tile boundary duplicates
- **WHEN** a plate appears in multiple overlapping tiles
- **THEN** the system SHALL use NMS to merge duplicate detections into a single box

#### Scenario: Disable tiling
- **WHEN** the user passes `--no-tiled`
- **THEN** the system SHALL use single-pass detection (letterbox full frame to 640x640)

### Requirement: GPU batch inference
When running with `onnxruntime-gpu`, the system SHALL batch multiple tiles into a single inference call for GPU efficiency.

#### Scenario: Batch inference with GPU
- **WHEN** onnxruntime has CUDAExecutionProvider available
- **THEN** tiles SHALL be batched (default batch size 8) for parallel GPU processing

#### Scenario: CPU fallback
- **WHEN** no GPU is available
- **THEN** tiles SHALL be processed sequentially on CPU

### Requirement: CLI detect-plates command
The system SHALL provide a `detect-plates` CLI command with: video path, `--output-dir`, `--start`, `--end`, `--threshold`, `--every-n`, `--tiled/--no-tiled`, `--model`.

#### Scenario: Basic tiled invocation
- **WHEN** the user runs `trailvideocut detect-plates video.mp4`
- **THEN** the system SHALL process frames with tiled detection and save annotated PNGs + `detections.csv`

#### Scenario: Custom model
- **WHEN** the user runs `trailvideocut detect-plates video.mp4 --model custom.onnx`
- **THEN** the system SHALL use the specified ONNX model for detection

### Requirement: Time range filtering
The command SHALL accept `--start` and `--end` options (in seconds) to limit detection to a specific time range.

#### Scenario: Start and end specified
- **WHEN** the user runs `trailvideocut detect-plates video.mp4 --start 10 --end 20`
- **THEN** only frames between 10s and 20s SHALL be processed

### Requirement: Annotated frame screenshots
For each processed frame, the system SHALL save a PNG with detection boxes drawn. Frames with no detections SHALL also be saved.

#### Scenario: Frame with detections
- **WHEN** a frame has detected plates
- **THEN** the saved PNG SHALL show colored rectangles with confidence labels

### Requirement: Detection log file
The system SHALL generate `detections.csv` with: frame_number, timestamp_s, x, y, w, h, x_px, y_px, w_px, h_px, confidence.

#### Scenario: CSV content
- **WHEN** detection completes
- **THEN** `detections.csv` SHALL contain a header row and one data row per detected plate box

### Requirement: Auto-download model
If the ONNX model is not cached, the command SHALL download it automatically with progress.

#### Scenario: First run
- **WHEN** the model file does not exist in the cache
- **THEN** the system SHALL download showing progress, then proceed

### Requirement: Progress display
The command SHALL show a Rich progress bar during processing.

#### Scenario: Progress during detection
- **WHEN** detection is running
- **THEN** a progress bar SHALL show current/total frames with ETA
