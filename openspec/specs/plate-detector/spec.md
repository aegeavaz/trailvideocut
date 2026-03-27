## ADDED Requirements

### Requirement: Detect plates in video frames
The system SHALL process video frames from a given time range and return bounding box coordinates for all detected license plates. Detection SHALL use an ONNX-based model loaded via OpenCV DNN. Results SHALL be returned as normalized coordinates (0-1 range) relative to the frame dimensions.

#### Scenario: Successful detection on a clip
- **WHEN** the detector is given a video file path, start time, and end time
- **THEN** it SHALL extract frames at the video's native FPS, run detection on each frame, and return a dictionary mapping frame numbers to lists of `PlateBox` objects

#### Scenario: No plates found in a frame
- **WHEN** a frame contains no detectable license plates
- **THEN** the frame SHALL be omitted from the results dictionary (no empty list entry)

#### Scenario: Multiple plates in a single frame
- **WHEN** a frame contains multiple license plates
- **THEN** all detected plates SHALL be returned as separate `PlateBox` entries for that frame

### Requirement: Configurable confidence threshold
The system SHALL accept a confidence threshold parameter (default 0.5). Only detections with confidence >= threshold SHALL be included in results.

#### Scenario: Low-confidence detection filtered out
- **WHEN** a plate is detected with confidence 0.3 and the threshold is 0.5
- **THEN** that detection SHALL NOT appear in the results

#### Scenario: High-confidence detection included
- **WHEN** a plate is detected with confidence 0.8 and the threshold is 0.5
- **THEN** that detection SHALL appear in the results with its confidence value preserved

### Requirement: Model loading and caching
The system SHALL load the ONNX model from a local cache directory. If the model file does not exist locally, the system SHALL download it on first use and cache it for subsequent runs.

#### Scenario: First run with no cached model
- **WHEN** the detector is initialized and no model file exists in the cache directory
- **THEN** the system SHALL download the model file, save it to the cache directory, and load it

#### Scenario: Subsequent run with cached model
- **WHEN** the detector is initialized and the model file exists in the cache directory
- **THEN** the system SHALL load the model directly without downloading

### Requirement: Progress reporting
The detector SHALL report progress as a fraction (frames processed / total frames) via a callback function, allowing the caller to update UI progress indicators.

#### Scenario: Progress callback invoked during detection
- **WHEN** detection is running on a clip with 100 frames
- **THEN** the progress callback SHALL be invoked at least once per 10 frames with the current progress fraction

### Requirement: Cancellation support
The detector SHALL check a cancellation flag between frames and stop processing early if cancellation is requested, returning partial results collected so far.

#### Scenario: Detection cancelled mid-clip
- **WHEN** the user cancels detection after 50 of 100 frames have been processed
- **THEN** the detector SHALL stop processing and return results for the 50 processed frames
