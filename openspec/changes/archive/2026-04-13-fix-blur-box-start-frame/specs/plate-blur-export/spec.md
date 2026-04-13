## MODIFIED Requirements

### Requirement: Apply Gaussian blur to detected plate regions during export
The system SHALL apply Gaussian blur to all detected plate bounding box regions when rendering the final video via FFmpeg. Blur SHALL be applied frame-by-frame using the stored plate coordinates for each clip. Only MP4 export SHALL apply blur; OTIO export SHALL remain unchanged. Blur SHALL only be applied to frames within the detection range; frames before the first detection or after the last detection in a clip SHALL NOT be blurred.

#### Scenario: Export with detected plates
- **WHEN** the user exports a video with plate detection data available for clips 0 and 2
- **THEN** the exported video SHALL have all plate regions in clips 0 and 2 blurred, and clips without plate data SHALL render without blur

#### Scenario: Export with no plate data
- **WHEN** the user exports a video with no plate detection data
- **THEN** the export SHALL proceed identically to the current behavior with no blur applied

#### Scenario: Export with blur disabled
- **WHEN** the user exports a video with plate data available but `plate_blur_enabled` is set to `False`
- **THEN** the export SHALL proceed without applying any plate blur

#### Scenario: Plate detection starts mid-clip
- **WHEN** a clip spans frames 0-200 and plate detections exist only for frames 100-180
- **THEN** frames 0-99 SHALL NOT have any blur applied, frames 100-180 SHALL have blur applied to the plate regions, and frames 181-200 SHALL NOT have any blur applied

#### Scenario: Frame outside detection range returns no boxes
- **WHEN** `_get_boxes_for_frame()` is called with a frame number before the first detection key or after the last detection key
- **THEN** the method SHALL return an empty list, not the nearest detection's boxes
