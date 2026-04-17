## Context

`PlateDetector` supports an optional phone/device filter (`exclude_phones=True`) that runs a secondary YOLOv8n COCO model, detects class 67 ("cell phone"), pads the detected box by 20 % on each side, and then drops any plate detection whose center lies inside that padded zone. Zones are refreshed every frame until the first zone is found and every N frames after that.

Today the filter is "invisible":
- Zones are held in a private instance attribute `PlateDetector._phone_zones` that only exists for the lifetime of a single `detect_clip()` call and is reset to `[]` at the start of each call.
- `ClipPlateData` stores only the final, post-filter `detections` dict — discarded plates and the zones that discarded them are unrecoverable.
- The Review page overlay (`PlateOverlayWidget`) only knows about `PlateBox` items from `ClipPlateData.detections`; it has no awareness of phone zones.

Operators tuning the detector need to verify two things visually:
1. The YOLO phone detector locates the phone correctly.
2. The 20 % padding and re-detect cadence produce a zone that matches the area the user expects the filter to cover on any given frame.

Stakeholders: the power user running plate detection from the Review page, and the CLI user using `--exclude-phones` who may benefit from verbose logging of zones (secondary, non-blocking).

Constraints:
- Zones must not be persisted to the on-disk sidecar plate file (debug-only data, not part of the plate contract).
- The change must not alter the filtering logic or mask any existing behavior — zones produced for debug rendering MUST be the exact same `(x, y, w, h)` tuples that `_filter_phone_zones` consumes.
- The overlay already handles resize, selection, right-click-add, blur-preview tiles; phone-zone rendering must not break any of those interactions.
- Detection runs on a worker thread; zones must cross the thread boundary through the existing result-signalling path rather than a new one.

## Goals / Non-Goals

**Goals:**
- Record the phone zones that were *active when each frame was processed*, keyed by frame number, for every frame in a detected clip.
- Surface those per-frame zones to the Review page without altering the sidecar file format.
- Render zones in the overlay with a visually distinct, non-interactive style so they cannot be confused with plate boxes or blur-preview tiles.
- Let the user toggle zone visibility independently of plate-box visibility.

**Non-Goals:**
- Do **not** change the filtering algorithm, padding, or re-detect cadence.
- Do **not** persist phone zones in sidecar files or any plate-export artifact (DaVinci Lua, blur export).
- Do **not** make zones editable, movable, or selectable; they are read-only debug geometry.
- Do **not** attempt to visualize *which* plate detections were rejected by the filter — that is a larger scope (would require preserving pre-filter boxes). Only the zones themselves are in scope.
- Do **not** show zones outside the Review page's plate overlay (e.g., on the timeline or export previews).

## Decisions

### Decision 1: Store zones per-frame on `ClipPlateData`, not on `PlateDetector`

**Chosen:** Add a new field `phone_zones: dict[int, list[tuple[float, float, float, float]]]` to `ClipPlateData` (or, if we prefer to keep `ClipPlateData` stable, on a sibling `ClipDebugData`). Populate it inside `_detect_clip_opencv` right after `update_phone_zones(frame)` — capturing whatever is currently in `self._phone_zones`, *including* the re-used zones from previous frames (which is the whole point: the user needs to know what was covering each frame).

**Alternatives considered:**
- *Accessor on the detector (e.g., `detector.last_zones`):* Works for single-frame `Detect Frame`, but can't survive the worker thread crossing for a full clip — the worker is disposed, so only data embedded in the returned `ClipPlateData` reaches the UI.
- *Only record zones when they change (sparse map):* Saves memory, but complicates the UI lookup (needs last-seen-zone logic) and the memory cost is tiny: ~32 bytes per frame for a typical 1–3 zone list, well under 1 MB for a multi-minute clip.

**Why per-frame, not per-refresh:** The refresh cadence (every N frames) is an implementation detail. Storing per-frame keeps the renderer trivially correct — "if frame F has zones, draw them" — and survives any future change to the refresh strategy.

### Decision 2: Persist zones in the plates sidecar (v2 schema)

**Chosen:** Extend the `.plates.json` sidecar to include a per-clip `phone_zones` block alongside `detections`. Bump the schema `version` from 1 to 2. Keep v1 readable — load as plates-only with an empty zones map.

**Why:** The feature graduated from "debug visualization of the current run" into behavior-affecting filter geometry: the same zones determine which plate detections get dropped. Forcing users to re-run detection just to see the filter after reopening the app is real friction on long clips. The zones are cheap to serialize (tiny JSON), tightly coupled to their plate data (same clip, same frames), and a single sidecar keeps the on-disk story simple.

**Why not a separate `.zones.json`:** Two files to manage, delete, and keep in sync. No upside over embedding.

**Alternatives considered:**
- *Keep ephemeral:* Original design. Clean debug/data separation but poor UX after app restarts.
- *Separate sidecar file:* Cleaner schema boundary but doubles the file-management surface.

### Decision 3: Render zones in `PlateOverlayWidget` paintEvent, as a separate pass *below* plate boxes

**Chosen:** Add `set_phone_zones(zones)` / `clear_phone_zones()` and a `_phone_zones_visible: bool` flag on `PlateOverlayWidget`. In `paintEvent`, draw zones *after* the background fill and *before* blur tiles + plate boxes, using:
- 2 px dashed border in a distinctive color (e.g., magenta `#E040FB` — not used anywhere else on the overlay today).
- Translucent fill (alpha ~30) in the same hue so the zone is legible but does not hide the video underneath.
- No resize handles, no mouse hit-testing participation.

**Alternatives considered:**
- *Render on a separate sibling widget:* More isolated but introduces another transparent top-level window with its own lifecycle, z-order, and Windows owner-window handling — the existing overlay already solved all of that. Reusing it is materially simpler.
- *Render after plate boxes:* Could cover important plate geometry; drawing below keeps zones as "background context" that plate boxes visibly sit on top of.

### Decision 4: UI control is a checkbox adjacent to "Exclude Phone"

**Chosen:** Add `QCheckBox("Show Phone Filter")` in the existing `settings_row` next to `_chk_exclude_phones` and `_spin_phone_gap`. Default unchecked. Enabled only when `_chk_exclude_phones.isChecked()` is true *and* the current clip's `phone_zones` is non-empty; disabled + unchecked otherwise.

**Why:** Keeps all phone-related controls together, follows the precedent of `_chk_show_plates` for the main overlay, and the enable/disable condition prevents the user from enabling a useless overlay when no zones exist to show.

### Decision 5: Wire zones through workers via the existing result signal

**Chosen:** The `ClipPlateData` object returned from the worker already makes the cross-thread trip. Because `phone_zones` is a new field on the same dataclass, no new Qt signal is needed. `ReviewPage` receives the `ClipPlateData`, stores it in `self._plate_data[clip_index]`, and pushes `data.phone_zones.get(current_frame, [])` into the overlay on every frame-change signal — the same path that already feeds `set_current_frame()`.

**Alternatives considered:**
- *New `phone_zones_updated` signal per frame:* Chatty and redundant; the data is already piggybacking on `ClipPlateData`.

## Risks / Trade-offs

- **[Risk] Memory overhead on very long clips** → Mitigation: zones are tuples of four floats; 3 zones/frame × 60 fps × 600 s ≈ 1 MB worst case — negligible. If a pathological case shows up, add a dedup/RLE step later without changing the public API.
- **[Risk] Users mistake the magenta zone for an editable plate** → Mitigation: distinct color + dashed border + zero hit-testing + a tooltip on the overlay's paint region explaining "phone filter zone (read-only)" (optional polish). The checkbox label "Show Phone Filter" (not "Show Plates") further disambiguates.
- **[Risk] Zones drift visually from the plate boxes due to coordinate-system bugs** → Mitigation: reuse the exact same `_norm_to_widget()` transform the plate boxes use. Add a unit test that feeds a known zone through the overlay and asserts pixel-perfect placement.
- **[Risk] "Detect Frame" (single-frame detection) path does not populate `phone_zones`** → Mitigation: also record zones in the single-frame detection code path. `detect_frame()` already calls `update_phone_zones()`, so exposing the result is a one-liner.
- **[Risk] Overlay now has two drawable geometry types; future maintainers may couple them** → Mitigation: keep `_phone_zones` state fully separate from `_clip_data.detections`, and document in the paint method that the two passes are independent.

## Migration Plan

This is a pure additive change:
1. Add new optional field to `ClipPlateData` with a default of `{}` — any existing sidecar files loaded from disk land with an empty zones map, which the overlay treats as "nothing to draw".
2. Ship detector changes first; the UI change can land in the same or a following PR. No rollout gate required.
3. Rollback: removing the field defaults to no overlay rendering; no migration needed in either direction.

## Open Questions

- Should "Show Phone Filter" default to **on** whenever `Exclude Phone` is on, to proactively surface the filter's behavior? Current design defaults it off to avoid visual clutter for users who trust the filter; revisit after usability testing.
- Should the CLI `--verbose` path print phone-zone summaries per frame (it currently prints per-box decisions only)? Low-cost follow-up — not in scope for this change.
