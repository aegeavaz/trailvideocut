## Why

The `PlateDetector` silently discards plate detections whose centers fall inside phone/device exclusion zones (`_filter_phone_zones`), but the user has no way to verify that these zones are placed correctly on the video. When the "Exclude Phone" filter produces unexpected results (e.g., a valid plate is dropped, or a phone region is missed), the only feedback today is the final set of surviving plate boxes — a black box. Operators tuning detection need to *see* the zone the filter is covering to tell whether the filter is doing the right thing.

## What Changes

- Capture the phone exclusion zones produced by `PlateDetector.update_phone_zones()` on every frame where they are refreshed, and persist them per-frame alongside plate detections so the UI can replay them.
- Extend `ClipPlateData` (or an adjacent data structure) with a per-frame phone-zones map so detection results carry the debug information from the worker thread back to the UI.
- Extend `PlateOverlayWidget` to render phone-zone rectangles in a visually distinct style (dashed border, contrasting color, not selectable / not editable) so they cannot be confused with plate boxes.
- Add a "Show Phone Filter" toggle in the Review page plate-controls row that is enabled only when `Exclude Phone` is enabled and zones exist; persists visibility state for the session.
- Ensure phone-zone rendering does not interfere with existing box interactions (selection, drag, resize, add-by-right-click, blur preview tiles).

## Capabilities

### New Capabilities
- `phone-filter-debug-overlay`: Visual debug overlay that renders the padded phone/device exclusion zones produced by the plate detector's `exclude_phones` filter, so operators can verify the filter geometry is correct on a per-frame basis.

### Modified Capabilities
- `plate-detector`: Detection results SHALL expose, per frame, the phone exclusion zones that were active when that frame was processed, so downstream consumers (UI, CLI verbose logs) can inspect them.
- `plate-overlay-ui`: The overlay SHALL render phone exclusion zones as non-interactive debug rectangles distinct from plate boxes, controlled by a separate visibility toggle.

## Impact

- **Code**:
  - `src/trailvideocut/plate/models.py` — add a per-frame phone-zones field to `ClipPlateData` (or a sibling dataclass).
  - `src/trailvideocut/plate/detector.py` — record zones per processed frame in `_detect_clip_opencv`; add a public accessor on `PlateDetector` for the zone list; no change to filtering semantics.
  - `src/trailvideocut/ui/plate_overlay.py` — new `set_phone_zones()` / `clear_phone_zones()` API; new paint pass drawing dashed rectangles; hit-testing unchanged.
  - `src/trailvideocut/ui/review_page.py` — new "Show Phone Filter" checkbox wired to overlay; subscribe to detection results to push zones into the overlay; keep in sync with frame navigation.
  - `src/trailvideocut/ui/workers.py` — forward per-frame phone zones from detector to the UI through the existing result channel.
- **Persistence**: Phone zones are written into the existing `.plates.json` sidecar alongside plate detections under a bumped schema version (v2). Legacy v1 sidecars still load with empty zones. Exported artifacts (DaVinci Lua, blur export) remain unaffected.
- **APIs / dependencies**: No new external dependencies. No breaking public API changes; `PlateDetector.detect_clip()` return type gains an optional field that older callers can ignore.
- **Tests**: New unit tests for detector zone recording; new overlay rendering test verifying zone rectangles appear with the debug style and do not register as selectable plate boxes.
