## Requirements

### Requirement: Apply Gaussian blur to detected plate regions during export
The system SHALL apply Gaussian blur to all detected plate bounding box regions when rendering the final video via FFmpeg. Blur SHALL be applied frame-by-frame using the stored plate coordinates for each clip. Only MP4 export SHALL apply blur; OTIO export SHALL remain unchanged.

#### Scenario: Export with detected plates
- **WHEN** the user exports a video with plate detection data available for clips 0 and 2
- **THEN** the exported video SHALL have all plate regions in clips 0 and 2 blurred, and clips without plate data SHALL render without blur

#### Scenario: Export with no plate data
- **WHEN** the user exports a video with no plate detection data
- **THEN** the export SHALL proceed identically to the current behavior with no blur applied

#### Scenario: Export with blur disabled
- **WHEN** the user exports a video with plate data available but `plate_blur_enabled` is set to `False`
- **THEN** the export SHALL proceed without applying any plate blur

### Requirement: Automatic blur strength based on plate dimensions
Blur intensity SHALL be determined automatically from the plate's pixel dimensions. There is no per-plate or global blur strength setting. All detected plates are blurred; to exclude a plate the user deletes the detection. `TrailVideoCutConfig` SHALL include a `plate_blur_enabled` field (bool, default True) that acts as a master toggle.

#### Scenario: All detected plates are blurred
- **WHEN** a frame has 3 detected plates of different sizes
- **THEN** the system SHALL apply Gaussian blur to all 3 plates, with kernel sizes proportional to each plate's dimensions

#### Scenario: Global blur disabled skips all blur
- **WHEN** `plate_blur_enabled` is `False` and plate data exists
- **THEN** the export SHALL not apply any blur

### Requirement: Apply blur during MoviePy composition with calibrated frame mapping
The system SHALL apply blur per-frame using MoviePy's `transform()` function during video composition. Before applying blur to a clip, the system SHALL calibrate the frame offset by comparing MoviePy's first decoded frame against source frames (content-based MSE matching). Segments without plate data SHALL pass through unchanged.

#### Scenario: Mixed segments with and without plates
- **WHEN** a cut plan has 5 segments and only segments 1 and 3 have plate data
- **THEN** only segments 1 and 3 SHALL have blur applied; segments 0, 2, and 4 SHALL render without blur processing

#### Scenario: Drift-tolerant blur boxes
- **WHEN** blur is applied to a frame and the plate moves between adjacent frames
- **THEN** the blur region SHALL be expanded to the bounding-box union of plate positions at frames N-1, N, and N+1, ensuring the plate is covered even with ±1 frame timing drift

### Requirement: Progress reporting during blur pre-processing
The system SHALL report blur processing progress to the user via the existing progress callback mechanism. Progress SHALL reflect the combined effort of pre-processing and FFmpeg assembly.

#### Scenario: Progress during blur processing
- **WHEN** blur pre-processing is running for a segment with 300 frames
- **THEN** the progress callback SHALL be invoked periodically with the current frame count and total frame count

### Requirement: Blur kernel size scales with plate dimensions
The Gaussian blur kernel size SHALL scale automatically with the plate's pixel dimensions. The formula SHALL be: `kernel_size = max(3, min(plate_pixel_w, plate_pixel_h))`, ensuring the kernel is always odd. Larger plates get proportionally stronger blur so the content is fully obscured.

#### Scenario: Large plate gets large kernel
- **WHEN** a plate region is 200x100 pixels
- **THEN** the Gaussian kernel size SHALL be 99 (odd, scaled from min dimension 100)

#### Scenario: Small plate gets small kernel
- **WHEN** a plate region is 40x20 pixels
- **THEN** the Gaussian kernel size SHALL be 19 (odd, scaled from min dimension 20)
