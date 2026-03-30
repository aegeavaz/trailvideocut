## Requirements

### Requirement: Zoom toward mouse cursor position
The system SHALL zoom the video view toward the point under the mouse cursor when the user scrolls to zoom. The scene point under the cursor SHALL remain at the same viewport position after the zoom operation completes.

#### Scenario: Zoom in on a specific area
- **WHEN** the user scrolls up (zoom in) with the mouse cursor positioned over the top-left quadrant of the video
- **THEN** the view SHALL zoom in and the scene content that was under the cursor SHALL remain under the cursor after the zoom

#### Scenario: Zoom out from a specific area
- **WHEN** the user scrolls down (zoom out) with the mouse cursor positioned over any point on the video
- **THEN** the view SHALL zoom out and the scene content that was under the cursor SHALL remain under the cursor after the zoom

#### Scenario: Zoom at minimum level
- **WHEN** the user scrolls down (zoom out) and the zoom level is already at 1.0 (fit-to-view)
- **THEN** the zoom level SHALL remain at 1.0 and the view SHALL not change

#### Scenario: Zoom at maximum level
- **WHEN** the user scrolls up (zoom in) and the zoom level is already at the maximum (5.0)
- **THEN** the zoom level SHALL remain at 5.0 and the view SHALL not change

### Requirement: Overlay synchronizes with cursor-centered zoom
The system SHALL update the plate overlay position and scale to match the zoomed and scrolled video view after a cursor-centered zoom operation.

#### Scenario: Overlay matches after zoom
- **WHEN** the user zooms in on the video with the mouse cursor
- **THEN** the plate overlay bounding boxes SHALL reposition to match the zoomed video frame area
