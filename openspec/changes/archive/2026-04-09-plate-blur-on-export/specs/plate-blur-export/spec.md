## ADDED Requirements

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

### Requirement: Per-plate blur strength control
Each `PlateBox` SHALL have a `blur_strength` field (float, 0.0 to 1.0) that controls the intensity of the Gaussian blur applied to that plate region. A value of 0.0 SHALL mean no blur; 1.0 SHALL mean maximum blur. The default value SHALL be 1.0.

#### Scenario: Plate with full blur strength
- **WHEN** a plate has `blur_strength=1.0` and the plate region is 80x40 pixels
- **THEN** the system SHALL apply a Gaussian blur with a kernel size proportional to the plate dimensions, rendering the plate content unreadable

#### Scenario: Plate with partial blur strength
- **WHEN** a plate has `blur_strength=0.5`
- **THEN** the system SHALL apply a Gaussian blur with half the maximum kernel size, partially obscuring the plate content

#### Scenario: Plate with zero blur strength
- **WHEN** a plate has `blur_strength=0.0`
- **THEN** the system SHALL skip blur for that plate, leaving it unmodified in the export

### Requirement: Global default blur strength configuration
`TrailVideoCutConfig` SHALL include a `plate_blur_strength` field (float, 0.0 to 1.0, default 1.0) that serves as the default blur strength for newly detected plates. It SHALL also include a `plate_blur_enabled` field (bool, default True) that acts as a master toggle.

#### Scenario: New plate inherits global default
- **WHEN** a plate is detected with the global `plate_blur_strength` set to 0.7
- **THEN** the plate's `blur_strength` SHALL be initialized to 0.7

#### Scenario: Global blur disabled skips all blur
- **WHEN** `plate_blur_enabled` is `False` and plate data exists
- **THEN** the export SHALL not apply any blur regardless of individual plate `blur_strength` values

### Requirement: Apply blur during MoviePy composition with calibrated frame mapping
The system SHALL apply blur per-frame using MoviePy's `transform()` function during video composition. Before applying blur to a clip, the system SHALL calibrate the frame offset by comparing MoviePy's first decoded frame against source frames (content-based MSE matching). Segments without plate data SHALL pass through unchanged.

#### Scenario: Mixed segments with and without plates
- **WHEN** a cut plan has 5 segments and only segments 1 and 3 have plate data
- **THEN** only segments 1 and 3 SHALL have blur applied via transform; segments 0, 2, and 4 SHALL render without blur processing

#### Scenario: Drift-tolerant blur boxes
- **WHEN** blur is applied to a frame and the plate moves between adjacent frames
- **THEN** the blur region SHALL be expanded to the bounding-box union of plate positions at frames N-1, N, and N+1, ensuring the plate is covered even with ±1 frame timing drift

### Requirement: Progress reporting during blur pre-processing
The system SHALL report blur processing progress to the user via the existing progress callback mechanism. Progress SHALL reflect the combined effort of pre-processing and FFmpeg assembly.

#### Scenario: Progress during blur processing
- **WHEN** blur pre-processing is running for a segment with 300 frames
- **THEN** the progress callback SHALL be invoked periodically with the current frame count and total frame count

### Requirement: Blur kernel size scales with plate dimensions
The Gaussian blur kernel size SHALL scale with the plate's pixel dimensions to ensure consistent visual blur regardless of plate size. The formula SHALL be: `kernel_size = max(3, int(blur_strength * min(plate_pixel_w, plate_pixel_h)))`, ensuring the kernel is always odd.

#### Scenario: Large plate gets large kernel
- **WHEN** a plate region is 200x100 pixels with `blur_strength=1.0`
- **THEN** the Gaussian kernel size SHALL be approximately 99 (odd, scaled from min dimension 100)

#### Scenario: Small plate gets small kernel
- **WHEN** a plate region is 40x20 pixels with `blur_strength=1.0`
- **THEN** the Gaussian kernel size SHALL be approximately 19 (odd, scaled from min dimension 20)
