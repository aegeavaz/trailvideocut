## MODIFIED Requirements

### Requirement: Model loading and caching
The system SHALL load the plate-detection ONNX model from a local cache directory, selecting the file to load based on the active model variant (`"n"`, `"s"`, or `"m"`). Each variant SHALL be cached under its own filename in the same cache directory so that switching between variants does not evict or overwrite another variant's cached file. If the cached file for the active variant does not exist locally, the system SHALL download it on first use from the URL registered for that variant and cache it for subsequent runs. The default variant SHALL be `"m"` (YOLOv11m) so that the out-of-box experience favours recall and box tightness; users who find per-frame latency too high MAY select `"s"` or `"n"` in the GUI or via `--plate-model`. A cached `"n"` ONNX left over from a pre-change install SHALL remain valid and re-usable without re-download when the user switches the combo/flag back to `"n"`.

#### Scenario: First run with no cached model for the active variant
- **WHEN** the detector is initialized with variant `"s"` and no `plate_detector_yolov11s.onnx` file exists in the cache directory
- **THEN** the system SHALL download the `"s"` model from its registered URL, save it as `plate_detector_yolov11s.onnx` in the cache directory, and load it

#### Scenario: Subsequent run with cached model for the active variant
- **WHEN** the detector is initialized with variant `"m"` and `plate_detector_yolov11m.onnx` exists in the cache directory
- **THEN** the system SHALL load the cached `"m"` model directly without downloading

#### Scenario: Default variant is "m"
- **WHEN** the detector is initialized without specifying a variant
- **THEN** the system SHALL resolve variant `"m"` and use the cache filename `plate_detector_yolov11m.onnx`

#### Scenario: Pre-change "n" cache remains valid after the default flip
- **WHEN** an existing user has only `plate_detector_yolov8n.onnx` cached (from a pre-change install) and the user selects variant `"n"` in the GUI or via `--plate-model n`
- **THEN** the system SHALL load the existing `"n"` cache file without re-download — the default-flip SHALL NOT invalidate previously-cached `"n"` ONNX files

#### Scenario: Switching variants preserves previously-downloaded caches
- **WHEN** variant `"n"` has already been downloaded, and the user then launches detection with variant `"s"` causing `"s"` to be downloaded, and then switches back to variant `"n"`
- **THEN** the `"n"` cache file SHALL still be present and used without re-download, and the `"s"` cache file SHALL also remain on disk

## ADDED Requirements

### Requirement: Selectable plate-detection model variant
The system SHALL support selection of the plate-detection model variant at detection-launch time from the set `{"n", "s", "m"}`. The selected variant SHALL determine which registered URL is used for download and which cache filename is used for load. The selection surface SHALL be available in both the GUI (a Review-page combo-box alongside the existing detection parameter widgets) and the CLI (a `--plate-model` flag on the `detect-plates` command). Both surfaces SHALL default to `"m"` (YOLOv11m, the largest / most-accurate variant). An unknown variant SHALL be rejected with a clear error naming the supported set.

#### Scenario: GUI combo-box drives the variant used for detection
- **WHEN** the user sets the Review-page "Plate Model" combo-box to `"s"` and clicks "Detect Plates"
- **THEN** the detection worker SHALL resolve and (if necessary) download the `"s"` model and the `PlateDetector` SHALL be constructed with the `"s"` cache path

#### Scenario: CLI flag drives the variant used for detection
- **WHEN** the user runs `detect-plates --plate-model n <video>`
- **THEN** the CLI handler SHALL resolve and (if necessary) download the `"n"` model and the `PlateDetector` SHALL be constructed with the `"n"` cache path

#### Scenario: Default selection is variant "m"
- **WHEN** the GUI combo-box is left at its initial selection, or the CLI is invoked without `--plate-model`
- **THEN** variant `"m"` SHALL be used

#### Scenario: Unknown variant is rejected
- **WHEN** a caller passes a variant string not in `{"n", "s", "m"}` to the model resolver
- **THEN** the resolver SHALL raise `ValueError` whose message names the supported variant set

#### Scenario: Detection pipeline is invariant under variant choice
- **WHEN** the same clip is processed with variants `"n"` and `"s"` (or `"m"`) under otherwise-identical parameters
- **THEN** the post-detection filter pipeline (geometry → phone-zone gate → vertical-position filter → tracker) SHALL run identically in all three cases — only the raw model outputs may differ, and no filter SHALL be enabled, disabled, or tuned based on the variant

### Requirement: Model variant registry
The system SHALL maintain a single in-code registry that maps each supported variant identifier to its `(download URL, cache filename)` pair. Lookups by both the GUI and the CLI SHALL resolve through this registry so that adding a new variant is a one-entry change. The `"n"` entry SHALL use the URL and cache filename in force before this change.

#### Scenario: Registry entry for variant "n" preserves pre-change values
- **WHEN** the registry is inspected for variant `"n"`
- **THEN** the entry SHALL contain the `ml-debi/yolov8-license-plate-detection` URL and the cache filename `plate_detector_yolov8n.onnx` exactly as they existed before this change

#### Scenario: Registry is the sole source of URL and filename for any variant
- **WHEN** `get_model_path(variant)` or `download_model(variant, …)` is called for any supported variant
- **THEN** the URL used for any download and the filename used for any cache read SHALL be sourced from the registry entry for that variant — no caller SHALL hard-code URLs or filenames for variants
