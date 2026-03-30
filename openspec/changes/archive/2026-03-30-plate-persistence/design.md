## Context

Plate detection results live in `ReviewPage._plate_data: dict[int, ClipPlateData]`, populated by the `PlateDetectionWorker`. Manual edits (add/move/resize/delete boxes) update the same in-memory dict via `PlateOverlayWidget`. When the session ends, everything is lost.

The data model is small: `ClipPlateData` holds a `clip_index` and a `detections` dict mapping `frame_number -> list[PlateBox]`. Each `PlateBox` has `x, y, w, h` (normalized floats), `confidence`, and `manual` flag.

## Goals / Non-Goals

**Goals:**
- Persist plate data as a JSON sidecar file next to the source video
- Auto-load on open when a sidecar exists
- Auto-save after detection completes and after each manual edit
- Allow clearing saved data to re-detect from scratch

**Non-Goals:**
- Database or binary format — JSON is human-readable and sufficient for the data volume
- Cross-video plate data sharing or merging
- Versioning or undo history within the sidecar file
- Plate blur/redaction (separate feature)

## Decisions

### 1. Sidecar file format: `<video_stem>.plates.json`

Place the file alongside the video (e.g., `trail.mp4` → `trail.plates.json`). This keeps data co-located and discoverable without a central registry.

**Alternative considered:** SQLite database — rejected because the data is small (typically <100KB), read/write is infrequent, and JSON is easier to inspect and debug.

**Alternative considered:** Pickle — rejected because it's not human-readable and has security concerns on untrusted input.

### 2. New `plate/storage.py` module

Single-responsibility module with `save_plates()` and `load_plates()` functions. Keeps serialization logic out of the UI layer.

Schema:
```json
{
  "version": 1,
  "video_file": "trail.mp4",
  "clips": {
    "0": {
      "clip_index": 0,
      "detections": {
        "42": [{"x": 0.1, "y": 0.2, "w": 0.05, "h": 0.03, "confidence": 0.92, "manual": false}]
      }
    }
  }
}
```

The `version` field allows future schema migrations without breaking existing files.

### 3. Auto-save triggers

- After `PlateDetectionWorker.finished` signal delivers results
- After any manual edit in `PlateOverlayWidget` (debounced, so rapid edits don't thrash disk)
- Save is fire-and-forget on the main thread (data is small, <1ms write)

### 4. Auto-load on `set_cut_plan()`

When `ReviewPage.set_cut_plan()` is called with the video path, check for a sidecar file. If found, load and populate `_plate_data` before the user interacts. Show a brief status message ("Loaded saved plates").

### 5. UI additions

- Status indicator in the plate controls area showing whether saved plate data was loaded
- "Clear Saved Plates" button that deletes the sidecar file and clears `_plate_data`
- "Detect Plates" re-runs detection and overwrites saved data (existing behavior, now also persists)

## Risks / Trade-offs

- **[Stale data]** If the user re-cuts the video with different clip boundaries, saved plate data won't match. → Mitigation: validate `clip_index` values against current `CutPlan.decisions` on load; discard mismatched entries and notify user.
- **[Disk permissions]** Video may be on a read-only mount. → Mitigation: catch `PermissionError` on save, show warning, continue without persistence.
- **[Large files]** Extremely long videos with many detections could produce large JSON. → Mitigation: for typical trail cam videos (<1hr, ~30 clips), data is well under 1MB. No action needed now.
