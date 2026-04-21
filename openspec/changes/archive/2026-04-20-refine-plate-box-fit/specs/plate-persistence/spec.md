## MODIFIED Requirements

### Requirement: Sidecar file format
The sidecar file SHALL use a versioned JSON schema containing the video filename, a version number, and a mapping of clip indices to their detection data. Each detection entry SHALL preserve `x`, `y`, `w`, `h`, `confidence`, and `manual` fields and SHALL OPTIONALLY include an `angle` field (floating-point degrees, centre-of-box rotation) whose presence indicates an oriented (rotated-rectangle) box. When `angle` is absent from a detection entry, readers SHALL treat the detection as axis-aligned (equivalent to `angle == 0.0`). Writers SHALL write the `angle` field only when its value is non-zero. Blur intensity is computed automatically from plate dimensions at render time and is not stored.

#### Scenario: Round-trip serialization (axis-aligned)
- **WHEN** axis-aligned plate data is saved and then loaded
- **THEN** all `PlateBox` fields (`x`, `y`, `w`, `h`, `confidence`, `manual`) and frame-to-box mappings SHALL be identical to the original data, and loaded boxes SHALL have `angle == 0.0`

#### Scenario: Round-trip serialization (oriented)
- **WHEN** plate data containing at least one oriented box (e.g. `angle == 12.5`) is saved and then loaded
- **THEN** that box SHALL round-trip with the same `angle` value (within floating-point tolerance of 1e-6) and all other fields SHALL be identical

#### Scenario: Load legacy sidecar without angle field
- **WHEN** a sidecar file written by an earlier version (no `angle` field on any detection) is loaded
- **THEN** the load SHALL succeed without error and every loaded box SHALL have `angle == 0.0`

#### Scenario: Writer omits the default angle
- **WHEN** plate data containing only axis-aligned boxes is serialized
- **THEN** the JSON output SHALL NOT contain an `angle` key on any detection entry, keeping the file diff-minimal relative to the pre-feature format
