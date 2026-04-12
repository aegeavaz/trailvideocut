## MODIFIED Requirements

### Requirement: New action buttons in plate controls panel
The system SHALL display the Plate Detection group box occupying the full width of the bottom section (no longer sharing horizontal space with a clip details panel). The bottom section SHALL have a fixed height of 160px. The button rows, settings rows, plate list, blur preview button, and progress bar SHALL remain functionally identical but benefit from the additional horizontal space.

#### Scenario: Button layout
- **WHEN** the review page is displayed with plate detection controls visible
- **THEN** the Plate Detection group box SHALL span the full width of the bottom section, with a first row containing "Detect Plates / Add Plate / Show Plates" and a second row containing "Detect Frame", "Clear Clip Plates", and "Clear Frame Plates" buttons

#### Scenario: Buttons enabled after detection
- **WHEN** plate detection has completed for at least one clip
- **THEN** "Detect Frame" is enabled if a clip is selected and video is loaded, "Clear Clip Plates" is enabled if the selected clip has plate data, and "Clear Frame Plates" is enabled if the current frame has plate boxes

#### Scenario: Buttons disabled initially
- **WHEN** the review page is first loaded with no plate data
- **THEN** all three new buttons SHALL be disabled

#### Scenario: Bottom section height
- **WHEN** the ReviewPage is displayed
- **THEN** the bottom section containing the Plate Detection panel SHALL have a fixed height of 160px
