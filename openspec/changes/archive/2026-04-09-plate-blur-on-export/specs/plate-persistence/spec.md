## MODIFIED Requirements

### Requirement: Sidecar file format
The sidecar file SHALL use a versioned JSON schema containing the video filename, a version number, and a mapping of clip indices to their detection data. Each detection entry SHALL preserve `x`, `y`, `w`, `h`, `confidence`, `manual`, and `blur_strength` fields. When loading a sidecar file that does not contain `blur_strength` for a plate entry, the system SHALL default to `1.0`.

#### Scenario: Round-trip serialization
- **WHEN** plate data is saved and then loaded
- **THEN** all `PlateBox` fields (`x`, `y`, `w`, `h`, `confidence`, `manual`, `blur_strength`) and frame-to-box mappings SHALL be identical to the original data

#### Scenario: Loading legacy sidecar without blur_strength
- **WHEN** a sidecar file saved before the blur feature (without `blur_strength` fields) is loaded
- **THEN** each `PlateBox` SHALL have `blur_strength` set to `1.0` (full blur)

#### Scenario: Save includes blur_strength
- **WHEN** a plate has `blur_strength=0.5` and the data is saved
- **THEN** the sidecar JSON SHALL include `"blur_strength": 0.5` for that plate entry
