## Requirements

### Requirement: Toggle blur preview on the review page
The review page SHALL provide a "Preview Blur" toggle button that enables or disables the blur preview. When enabled, plate regions on the current frame SHALL be rendered with the actual Gaussian blur effect applied, matching the export output. When disabled, the overlay SHALL revert to the standard bounding box display.

#### Scenario: Enable blur preview
- **WHEN** the user clicks the "Preview Blur" toggle while plates are detected on the current frame
- **THEN** the overlay SHALL display blurred plate regions instead of (or in addition to) the box outlines

#### Scenario: Disable blur preview
- **WHEN** the user disables the "Preview Blur" toggle
- **THEN** the overlay SHALL clear all blurred pixmaps and display only bounding box outlines as before

#### Scenario: Toggle available only with plate data
- **WHEN** no plate data exists for the current clip
- **THEN** the "Preview Blur" toggle SHALL be disabled or hidden

### Requirement: Blur preview updates on frame change
When blur preview is enabled, the overlay SHALL update the blurred plate regions whenever the displayed frame changes (seek, step forward/backward, or playback position change). The update SHALL use the plate data for the new frame.

#### Scenario: User steps to next frame with plates
- **WHEN** blur preview is enabled and the user steps to frame 150 which has 2 detected plates
- **THEN** the overlay SHALL grab frame 150, apply Gaussian blur to both plate regions, and display the blurred patches

#### Scenario: User steps to frame without plates
- **WHEN** blur preview is enabled and the user steps to a frame with no detected plates
- **THEN** the overlay SHALL display no blurred patches (clear any previous pixmaps)

#### Scenario: Frame change during playback
- **WHEN** blur preview is enabled and the video is playing
- **THEN** the overlay SHALL update blurred patches at a throttled rate to avoid stacking frame grabs, with updates no more frequent than once every 100ms

### Requirement: Grab current video frame via OpenCV for preview
The system SHALL use OpenCV (`cv2.VideoCapture`) to read the current video frame by seeking to the timestamp corresponding to the player's current position. The frame grab SHALL run in a background thread to avoid blocking the UI.

#### Scenario: Frame grab completes successfully
- **WHEN** the overlay requests frame 150 at timestamp 5.0s
- **THEN** the system SHALL open the source video, seek to 5.0s, read one frame, and return it as a numpy array

#### Scenario: Frame grab cancelled by new seek
- **WHEN** a frame grab is in progress and the user seeks to a different frame
- **THEN** the pending grab SHALL be cancelled or its result discarded, and a new grab SHALL be initiated for the new frame

### Requirement: Blur preview uses same blur algorithm as export
The blur preview SHALL apply the same `cv2.GaussianBlur` with the same kernel size calculation as the export pipeline, ensuring visual consistency between preview and final output.

#### Scenario: Preview matches export blur
- **WHEN** a plate region is visible in the preview with blur enabled
- **THEN** the blur appearance SHALL be visually identical to the same plate in the exported video (auto-scaled kernel based on plate dimensions)

### Requirement: Blurred regions rendered as QPixmap tiles on overlay
The `PlateOverlayWidget` SHALL store blurred plate regions as `QPixmap` tiles and paint them in `paintEvent()` at the correct normalized positions. The pixmaps SHALL be painted before the bounding box outlines so boxes remain visible on top of the blur.

#### Scenario: Blurred pixmap positioned correctly
- **WHEN** a plate at normalized position (0.4, 0.2, 0.1, 0.05) is blurred
- **THEN** the blurred QPixmap SHALL be painted at the same widget-pixel position as the bounding box, covering the plate region exactly

#### Scenario: Blur intensity proportional to plate size
- **WHEN** plate A is 40x20 pixels and plate B is 200x100 pixels
- **THEN** the preview SHALL show plate B with a stronger blur kernel than plate A, matching the automatic area-based scaling used in export
