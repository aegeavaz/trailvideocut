## Why

Must-include marks are currently persisted only when the user clicks **Save Marks**, and only restored when they click **Load Marks** and navigate a file dialog. That is inconsistent with sibling features — exclusion ranges (`<stem>.exclusions.json`) auto-save on every edit and auto-load when the video is opened — and it routinely causes users to lose work when they close the app without remembering to save. The marks file itself is a bare JSON array with no schema version or filename binding, so sidecars get orphaned from their video and corrupt files crash the load flow.

## What Changes

- Auto-save marks to `{video_stem}.marks.json` after every mutation (add, remove, clear), matching the exclusion-range pattern.
- Auto-load marks from the sidecar when the user opens a video in the Setup page; absent/invalid sidecars yield an empty list, never a crash or user-facing dialog.
- **BREAKING** (file format): Upgrade the sidecar to a versioned object `{"version": 1, "video_filename": str, "marks": [float, ...]}`. Loader also accepts the legacy bare-array format for one release so existing sidecars keep working.
- Validate on load: unknown version, filename mismatch, or malformed entries are logged and discarded (return empty list), never raise.
- Remove the **Save Marks** and **Load Marks** buttons from the Marks tab; keep **+ Add Mark**, **Remove Selected**, and **Clear All**.
- Update `README.md` with a documented list of Setup-page keyboard shortcuts (including `A` to add a mark at the current frame and `D` to delete the selected mark) and a short "Marks" section explaining auto-persistence.

## Capabilities

### New Capabilities
- `marks-persistence`: Data model, sidecar serialization, and auto-save/auto-load lifecycle for must-include marks, mirroring the `source-exclusion-ranges` storage contract.

### Modified Capabilities
<!-- None — no existing spec governs marks. The Setup-page UI changes are implementation of the new capability and do not modify an existing spec. -->

## Impact

- **Code**: New `src/trailvideocut/video/marks.py` module (dataclass-free — marks are plain floats — plus `save_marks` / `load_marks` / `get_marks_path` / `delete_marks`). Refactor `src/trailvideocut/ui/setup_page.py` to remove the Save/Load buttons and hook auto-save into `_add_mark` / `_remove_mark` / `_clear_marks`, and to call `load_marks` from `_browse_video` alongside the existing `_auto_load_exclusions` call.
- **Data**: Existing `.marks.json` sidecars in the wild are bare JSON arrays; the loader accepts them as a legacy path and will rewrite to the versioned schema on the next mutation.
- **Docs**: `README.md` GUI section gains a keyboard-shortcut table and a Marks subsection.
- **Tests**: New `tests/test_video_marks.py` (unit tests for save/load round-trip, legacy format, version/filename mismatch, corrupt file, permission denied). Existing setup-page tests (if any) updated for the removed buttons.
- **Dependencies**: None (stdlib `json`, `pathlib`, `logging`).
