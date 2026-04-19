## MODIFIED Requirements

### Requirement: Blur size auto-scaling by relative plate area
The Fusion Blur node's XBlurSize SHALL be auto-scaled based on the plate's bounding-box area (`w × h`) relative to all plates in the clip. The smallest plate area maps to XBlurSize=1.5, the largest to XBlurSize=2.5, with linear interpolation for intermediate sizes. All detected plates are included in the composition. Both code paths that emit XBlurSize keyframes — the offline Lua-script generator and the in-Resolve Python automation script — SHALL use this same range.

#### Scenario: Smallest plate in clip
- **WHEN** a plate has the smallest bounding-box area in the clip
- **THEN** the Fusion Blur node SHALL have XBlurSize=1.5

#### Scenario: Largest plate in clip
- **WHEN** a plate has the largest bounding-box area in the clip
- **THEN** the Fusion Blur node SHALL have XBlurSize=2.5

#### Scenario: All plates same size
- **WHEN** all plates in the clip have the same bounding-box area
- **THEN** all Fusion Blur nodes SHALL have XBlurSize=1.5

#### Scenario: Intermediate plate area
- **WHEN** a plate's bounding-box area lies exactly midway between the clip's smallest and largest plate areas
- **THEN** the Fusion Blur node SHALL have XBlurSize=2.0 (the midpoint of the [1.5, 2.5] range)
