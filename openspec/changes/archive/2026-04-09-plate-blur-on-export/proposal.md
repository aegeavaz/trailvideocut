## Why

License plates detected during the review phase are currently only visualized as overlays in the UI but are completely ignored during video export. Users need the ability to blur detected plates in the exported video to protect privacy and comply with regulations. Per-plate blur control is essential since different plates may require different blur intensities depending on distance, angle, or artistic intent.

## What Changes

- Integrate plate data into the FFmpeg export pipeline so detected plates are blurred in the rendered output video.
- Add a per-plate blur intensity setting (configurable from the UI) that controls the strength of the Gaussian blur applied to each plate's bounding box region.
- Add a global default blur strength setting in the export configuration.
- Extend the `PlateBox` model with a `blur_strength` field that persists alongside existing plate data.
- Build FFmpeg filter graph expressions that apply boxblur filters at the correct frame ranges and pixel coordinates for each detected plate.
- Provide a UI control on the review page (per-plate) and export page (global default) to adjust blur intensity.
- Add a blur preview toggle on the review page that renders blurred plate regions directly on the overlay, giving users a real-time preview of how the blur will look in the final export. The preview grabs the current video frame via OpenCV, applies Gaussian blur to plate regions, and paints the blurred patches on the overlay widget.

## Capabilities

### New Capabilities
- `plate-blur-export`: Applying plate blur filters during FFmpeg video assembly, including filter graph generation, per-plate blur strength, and frame-accurate application of blur regions.
- `plate-blur-preview`: Live blur preview on the review page overlay. Grabs the current frame via OpenCV, applies Gaussian blur to plate regions, and renders the blurred patches on the `PlateOverlayWidget` as QPixmap tiles. Toggled via a button on the review page.

### Modified Capabilities
- `plate-persistence`: The `PlateBox` model gains a `blur_strength` field that must be serialized/deserialized in the sidecar JSON file. The sidecar version may need to be bumped.
- `plate-overlay-ui`: The overlay widget needs a per-plate blur strength control (e.g., slider or input on selection) so users can adjust blur intensity per plate.

## Impact

- **Code**: `assembler.py` (FFmpeg filter graph construction), `models.py` (PlateBox dataclass), `storage.py` (sidecar serialization), `plate_overlay.py` (blur preview rendering), `config.py` (default blur setting), `review_page.py` / export page (UI wiring).
- **Dependencies**: No new external dependencies. Uses FFmpeg's built-in `boxblur` filter. OpenCV (`cv2`) already present for plate detection, reused for frame grabbing and blur.
- **Data**: Sidecar `.plates.json` format gains `blur_strength` field; existing files without the field should default gracefully.
- **Performance**: FFmpeg filter complexity increases proportionally with the number of plate regions, but boxblur is computationally cheap. Blur preview grabs a single frame on demand (not continuous), so overhead is negligible during review.
