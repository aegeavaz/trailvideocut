## Context

The plate detection UI in `review_page.py` currently offers clip-level detection ("Detect Plates" button) and a global "Clear Saved Plates" button. Detection results are stored per-frame in `ClipPlateData.detections: dict[int, list[PlateBox]]`, and the detector already supports single-frame inference via `detect_frame()` / `detect_frame_tiled()`. The overlay, storage, and merge logic all operate at per-frame granularity. This change adds three new buttons for finer-grained plate management.

## Goals / Non-Goals

**Goals:**
- Allow re-detecting plates on a single frame without re-processing the entire clip.
- Allow clearing all plates (auto + manual) for the selected clip.
- Allow clearing all plates (auto + manual) for the current frame.
- Preserve the existing merge behavior (manual plates preserved on re-detection) for single-frame detection.
- Keep all new operations synchronous on the UI thread (single-frame detection is fast enough — ~50-200ms).

**Non-Goals:**
- Changing the clip-level detection workflow or worker threading model.
- Adding undo/redo for plate operations.
- Adding confirmation dialogs for frame-level clearing (too granular; clip-level clearing will have confirmation).

## Decisions

### D1: Single-frame detection runs synchronously (no worker thread)

**Rationale:** `detect_frame_tiled()` processes one frame in ~50-200ms, well under the ~100ms threshold for perceived UI lag. Spawning a `QThread` + signals for this adds complexity without benefit. The existing `PlateDetectionWorker` is designed for multi-frame clip processing with progress reporting.

**Alternative considered:** Reusing `PlateDetectionWorker` with a single-frame clip range — rejected because the threading overhead, progress UI, and cancel logic are unnecessary for a sub-second operation.

### D2: New buttons placed in the existing `btn_row` layout

**Rationale:** The plate controls panel already has a horizontal button row containing "Detect Plates", "Add Plate", and "Show Plates". Adding buttons here maintains visual grouping. To avoid overcrowding, the three new buttons will be placed in a second row below the existing one.

**Alternative considered:** A dropdown menu on "Detect Plates" — rejected because it hides functionality and adds clicks.

### D3: Clear Clip Plates requires confirmation; Clear Frame Plates does not

**Rationale:** Clearing an entire clip's plates is a higher-impact action (potentially hundreds of frames of data). A `QMessageBox.question` confirmation dialog prevents accidental data loss. Clearing a single frame's plates is low-impact and easily recoverable by re-running detection, so no confirmation needed.

### D4: Reuse existing PlateDetector instance

**Rationale:** Single-frame detection needs the same model and configuration as clip detection. Rather than creating a new detector per click, we lazily initialize and cache a `PlateDetector` instance on `ReviewPage` (similar to how `_plate_worker` holds the worker). The detector is instantiated on first use with current UI settings and recreated if settings change.

**Alternative considered:** Always creating a fresh detector — rejected due to ONNX model load time (~1-2s).

### D5: Frame number resolved from player position

**Rationale:** The current frame number is already computed as `round(self._player.current_time * self._player.fps)` throughout the codebase (see `_update_plate_overlay_frame`, `_sync_overlay_to_current_clip`). The new operations will use the same calculation for consistency.

## Risks / Trade-offs

- **[Risk] Single-frame detection uses UI-thread blocking** → Mitigated by the fast execution time (~50-200ms). If a user has an unusually slow CPU, they may perceive a brief freeze. Acceptable trade-off vs. threading complexity.
- **[Risk] Detector cache may use stale settings** → Mitigated by comparing current UI settings on each invocation and recreating the detector if they differ.
- **[Risk] Clearing clip plates is irreversible** → Mitigated by confirmation dialog. User can also re-run detection to recover auto-detected plates.
