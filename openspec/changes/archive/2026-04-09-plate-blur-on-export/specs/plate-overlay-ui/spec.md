## ADDED Requirements

### Requirement: Per-plate blur strength slider on selection
When a plate bounding box is selected in the overlay, the review page SHALL display a blur strength slider (range 0.0 to 1.0) that controls the `blur_strength` value for that specific plate. Changes to the slider SHALL update the plate data and trigger a save.

#### Scenario: User selects a plate and adjusts blur strength
- **WHEN** the user selects a detected plate box and moves the blur strength slider to 0.6
- **THEN** the plate's `blur_strength` SHALL be updated to 0.6 and the change SHALL be persisted to the sidecar file

#### Scenario: No plate selected hides the slider
- **WHEN** no plate box is selected in the overlay
- **THEN** the blur strength slider SHALL be hidden or disabled

#### Scenario: Switching between plates updates slider value
- **WHEN** the user selects plate A (blur_strength=0.3) then selects plate B (blur_strength=0.8)
- **THEN** the slider SHALL update to reflect each plate's current blur_strength value

### Requirement: Blur strength visual indicator on plate overlay
The overlay SHALL display the blur strength value as a small label on each plate box when blur strength differs from the default (1.0), providing visual feedback about per-plate blur settings.

#### Scenario: Plate with non-default blur strength shows label
- **WHEN** a plate has `blur_strength=0.5`
- **THEN** the overlay SHALL display "50%" near the plate box

#### Scenario: Plate with default blur strength shows no label
- **WHEN** a plate has `blur_strength=1.0`
- **THEN** no blur label SHALL be displayed on the plate box
