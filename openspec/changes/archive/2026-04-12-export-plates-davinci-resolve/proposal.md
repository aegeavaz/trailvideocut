## Why

The current DaVinci Resolve export (OTIO) only carries timeline structure (in/out points, transitions) but discards all plate blur information. Users who detect and configure plate blur in the app must then manually recreate those blur regions in Resolve. This defeats the purpose of the detection workflow when the final edit happens in Resolve.

## What Changes

- Embed plate detection data (per-frame bounding boxes, blur strength) as OTIO clip metadata so the plate information travels with the timeline file
- Generate a companion DaVinci Resolve automation script (Python) alongside the `.otio` file that reads the embedded plate data and programmatically adds Fusion blur compositions (keyframed RectangleMask with Blur nodes) to each clip
- Auto-execute the companion script via WSL interop (calling Windows Python) when DaVinci Resolve Studio 20+ is running — minimum friction, one-click export + apply
- Fall back gracefully when Resolve is unavailable: save the companion script for manual execution later
- Map plate coordinates from source-video frame numbers to timeline-relative frame numbers so blur regions align correctly after the edit cuts
- Add UI controls on the export page: "Include plate blur data in OTIO" and "Auto-apply in Resolve" checkboxes, visible only in DaVinci export mode

## Capabilities

### New Capabilities
- `davinci-plate-export`: Embedding plate blur data in OTIO metadata, generating a DaVinci Resolve automation script, and auto-applying Fusion blur compositions via WSL interop with DaVinci Resolve Studio 20+

### Modified Capabilities
- (none)

## Impact

- **Code**: `editor/exporter.py` (DaVinciExporter) — embed plate metadata in OTIO clips, trigger script generation + WSL interop execution
- **Code**: `editor/resolve_script.py` (**new**) — generate self-contained companion script, WSL interop execution logic
- **Code**: `ui/export_page.py` — add DaVinci plate blur checkboxes and auto-apply toggle
- **Code**: `ui/workers.py` — pass plate_data to DaVinciExporter
- **Code**: `ui/main_window.py` — wire resolve_apply_blur config from render settings
- **Code**: `config.py` — add `resolve_apply_blur` field
- **Dependencies**: No new dependencies (OTIO metadata is built-in; companion script uses DaVinci's own `DaVinciResolveScript` module available inside Resolve)
