## Why

The current plate detection UI only supports running detection across entire clips (or all clips). Users frequently need finer-grained control: re-detecting a single frame after adjusting parameters, or clearing plates from a specific frame or clip without wiping the entire project. These per-frame and per-clip actions reduce wasted work and give users precise control over their plate annotation workflow.

## What Changes

- **New "Detect Current Frame" button**: Re-runs plate detection on the currently displayed frame only, replacing auto-detected plates for that frame while preserving manual ones.
- **New "Clear Clip Plates" button**: Deletes all plates (both detected and manual) for the currently selected clip.
- **New "Clear Frame Plates" button**: Deletes all plates (both detected and manual) for the currently displayed frame.

## Capabilities

### New Capabilities
- `frame-plate-detection`: Single-frame plate detection that runs the detector on the current frame and merges results back into the clip's plate data.
- `plate-clearing-actions`: Per-clip and per-frame plate clearing operations with confirmation and persistence.

### Modified Capabilities
- `plate-overlay-ui`: New buttons added to the plate controls panel; button enable/disable state must reflect current context (frame loaded, plates present).
- `plate-detection-workflow`: Detection entry point extended to support single-frame mode alongside existing clip/all-clips modes.

## Impact

- **UI**: `review_page.py` — new buttons in the plate controls section, new signal handlers.
- **Detection**: `detector.py` — existing `detect_frame` / `detect_frame_tiled` methods already support single-frame detection; need a thin integration layer.
- **Storage**: `storage.py` — no schema changes; existing save/load handles per-frame granularity already.
- **Models**: `models.py` — no changes; `ClipPlateData.detections` dict already supports per-frame manipulation.
- **Overlay**: `plate_overlay.py` — may need refresh after clearing operations.
