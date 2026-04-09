## Requirements

### Requirement: Save plate data to sidecar file
The system SHALL serialize all `ClipPlateData` to a JSON sidecar file named `<video_stem>.plates.json` in the same directory as the source video. The file SHALL include a `version` field and the video filename for validation.

#### Scenario: Save after detection completes
- **WHEN** the plate detection worker finishes and delivers results
- **THEN** the system SHALL write all plate data to the sidecar file, creating it if it does not exist or overwriting if it does

#### Scenario: Save after manual box edit
- **WHEN** the user adds, moves, resizes, or deletes a plate bounding box
- **THEN** the system SHALL save the updated plate data to the sidecar file

#### Scenario: Save with write permission error
- **WHEN** the system attempts to save but the video directory is read-only
- **THEN** the system SHALL display a warning message and continue without persistence

### Requirement: Load plate data from sidecar file
The system SHALL check for a sidecar file when a video is opened with a cut plan. If found, the system SHALL deserialize the plate data and populate the in-memory plate data store.

#### Scenario: Sidecar file exists on open
- **WHEN** the user opens a video that has a corresponding `.plates.json` file
- **THEN** the system SHALL load the plate data and display a status message indicating plates were loaded

#### Scenario: No sidecar file on open
- **WHEN** the user opens a video with no corresponding `.plates.json` file
- **THEN** the system SHALL start with empty plate data (existing behavior)

#### Scenario: Sidecar file has mismatched clip indices
- **WHEN** the loaded plate data contains clip indices that do not exist in the current cut plan
- **THEN** the system SHALL discard those entries and keep only valid clip data

#### Scenario: Sidecar file is corrupted or invalid
- **WHEN** the sidecar file cannot be parsed as valid JSON or has an unrecognized version
- **THEN** the system SHALL discard the file contents, show a warning, and start with empty plate data

### Requirement: Clear saved plate data
The system SHALL provide a way for the user to delete the sidecar file and clear all in-memory plate data, allowing a fresh start.

#### Scenario: User clears saved plates
- **WHEN** the user triggers "Clear Saved Plates"
- **THEN** the system SHALL delete the sidecar file from disk and clear all in-memory plate data

#### Scenario: Clear when no saved data exists
- **WHEN** the user triggers "Clear Saved Plates" but no sidecar file exists
- **THEN** the system SHALL clear in-memory plate data without error

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
