## Purpose

Persist must-include marks (timestamps the clip selector pins into the final edit) to a JSON sidecar next to the video, so that adding, removing, or clearing marks in the Setup page survives restarts without explicit Save/Load actions. Mirrors the sidecar contract already used for exclusion ranges.

## Requirements

### Requirement: Marks sidecar path convention

The system SHALL persist must-include marks to a JSON sidecar file located next to the video, named by replacing the video's extension with `.marks.json` (e.g. `ride.mp4` → `ride.marks.json`). The resolver SHALL be a pure function of the video path — no network, no user dialog, no environment lookup.

#### Scenario: Sidecar path derived from video path

- **WHEN** `get_marks_path` is called with `/videos/ride.mp4`
- **THEN** the function SHALL return `/videos/ride.marks.json`

#### Scenario: Sidecar path for video without extension

- **WHEN** `get_marks_path` is called with a video path that has no extension (e.g. `/videos/ride`)
- **THEN** the function SHALL return a path with `.marks.json` appended (`/videos/ride.marks.json`), matching the behaviour of `Path.with_suffix(".marks.json")`

### Requirement: Marks sidecar schema

The system SHALL write marks sidecars as a JSON object with three fields: `version` (integer, currently `1`), `video_filename` (string, the basename of the source video), and `marks` (array of numbers, each a timestamp in seconds). The on-disk representation SHALL be UTF-8, indented for human readability, and SHALL list marks sorted ascending.

#### Scenario: Sidecar written with versioned schema

- **WHEN** `save_marks` is called with a non-empty list of floats
- **THEN** the file at `get_marks_path(video)` SHALL contain a JSON object with keys `version` (set to `1`), `video_filename` (set to `Path(video).name`), and `marks` (a JSON array of the supplied floats, sorted ascending)

#### Scenario: Sidecar written for empty mark list

- **WHEN** `save_marks` is called with an empty list
- **THEN** the file SHALL be written with `marks: []` rather than deleted, so subsequent auto-loads see "no marks for this video" rather than "sidecar missing"

### Requirement: Auto-load on video open

The Setup page SHALL call `load_marks` immediately after a video path is resolved (by file-dialog selection or otherwise) and SHALL populate its in-memory mark list from the return value. A missing or invalid sidecar SHALL yield an empty mark list with no user-facing dialog.

#### Scenario: Video opened with existing sidecar

- **WHEN** the user selects `ride.mp4` in the Setup page and `ride.marks.json` exists on disk with valid content
- **THEN** the Setup page SHALL display the persisted marks as chips in the Marks tab and the video scrubber SHALL render the mark positions, without the user invoking any additional action

#### Scenario: Video opened with no sidecar

- **WHEN** the user selects a video whose sidecar does not exist
- **THEN** the Setup page SHALL display an empty Marks list and SHALL NOT show any error or warning to the user

#### Scenario: Video opened with corrupt sidecar

- **WHEN** the user selects a video whose sidecar exists but is not valid JSON (or fails schema validation)
- **THEN** the Setup page SHALL display an empty Marks list, the loader SHALL log a warning naming the offending file, and no exception SHALL propagate to the UI

### Requirement: Auto-save on every mutation

The Setup page SHALL call `save_marks` after any operation that mutates the in-memory mark list — specifically: add at current position, remove selected, and clear-all. The save SHALL occur after the in-memory list is updated and sorted, so the sidecar always mirrors the on-screen state.

#### Scenario: Add mark persists immediately

- **WHEN** the user presses `A` (or clicks "+ Add Mark at Current Position") while a video is loaded
- **THEN** the system SHALL append the current player time to the in-memory list, refresh the UI, and write the updated list to the sidecar before the next event is processed

#### Scenario: Remove mark persists immediately

- **WHEN** the user removes the selected mark (via the button or `D` shortcut)
- **THEN** the system SHALL delete the entry from the in-memory list, refresh the UI, and overwrite the sidecar with the shortened list

#### Scenario: Clear all persists immediately

- **WHEN** the user clicks "Clear All"
- **THEN** the system SHALL empty the in-memory list, refresh the UI, and overwrite the sidecar with an empty `marks` array

### Requirement: Filename-mismatch guard

The loader SHALL discard any sidecar whose stored `video_filename` field does not match the basename of the video currently being opened, returning an empty list and logging a warning. This prevents sidecars from following renamed or misplaced video files into an unrelated project.

#### Scenario: Sidecar from renamed video rejected

- **WHEN** `load_marks` is called with `trip2.mp4` and the sidecar at `trip2.marks.json` has `"video_filename": "trip1.mp4"`
- **THEN** the loader SHALL return an empty list and SHALL log a warning that names both the stored and expected filenames

### Requirement: Version-mismatch guard

The loader SHALL recognise exactly the version values in its supported set (initially `{1}`). An unknown version SHALL cause the loader to discard the file, log a warning that identifies the offending version, and return an empty list.

#### Scenario: Unknown version rejected

- **WHEN** `load_marks` reads a sidecar whose JSON object contains `"version": 99`
- **THEN** the loader SHALL return an empty list and SHALL log a warning that names `99` and the supported versions

### Requirement: Legacy bare-array sidecar accepted

The loader SHALL accept sidecars whose top-level JSON value is a flat array of numbers — the format written by earlier releases — and SHALL treat each numeric entry as a mark timestamp. Non-numeric entries in a legacy array SHALL cause the entire file to be discarded (empty list returned, warning logged) rather than silently dropping individual entries, to avoid masking corruption. The next `save_marks` call SHALL overwrite the file with the current versioned schema.

#### Scenario: Legacy format loads successfully

- **WHEN** `load_marks` reads a sidecar whose content is exactly `[1.2, 3.4, 5.6]`
- **THEN** the loader SHALL return a sorted list `[1.2, 3.4, 5.6]` and SHALL NOT raise

#### Scenario: Legacy format with non-numeric entry rejected

- **WHEN** `load_marks` reads a sidecar whose content is `[1.2, "oops", 5.6]`
- **THEN** the loader SHALL return an empty list and SHALL log a warning identifying the malformed file

#### Scenario: Legacy file upgraded on next save

- **WHEN** a legacy-format sidecar is loaded successfully and the user then adds a mark
- **THEN** the auto-save SHALL overwrite the file with the versioned schema (`{"version": 1, "video_filename": ..., "marks": [...]}`)

### Requirement: Best-effort write under I/O failure

`save_marks` SHALL catch `PermissionError` and `OSError`, log a warning identifying the path and the error, and return normally. The in-memory mark list SHALL remain unchanged. The system SHALL NOT display a user-facing dialog on write failure.

#### Scenario: Write fails on read-only location

- **WHEN** the sidecar path is under a read-only directory and `save_marks` is called
- **THEN** the call SHALL return without raising, a warning SHALL be logged naming the path, and the in-memory mark list SHALL remain intact so the user can continue working in-session

### Requirement: Delete helper

The module SHALL expose `delete_marks(video_path)` that removes the sidecar file if it exists and is a no-op if it does not. The helper SHALL log (not raise) on unexpected I/O errors.

#### Scenario: Delete removes existing sidecar

- **WHEN** `delete_marks` is called for a video whose sidecar exists
- **THEN** the sidecar file SHALL no longer exist after the call returns

#### Scenario: Delete is idempotent when sidecar is missing

- **WHEN** `delete_marks` is called for a video whose sidecar does not exist
- **THEN** the call SHALL return without raising and without logging a warning

### Requirement: Save and Load buttons removed from Marks tab

The Setup page's Marks tab SHALL NOT present "Save Marks" or "Load Marks" buttons. The tab SHALL retain the "+ Add Mark at Current Position", "Remove Selected", and "Clear All" controls.

#### Scenario: Marks tab button set

- **WHEN** the Setup page is rendered and the Marks tab is active
- **THEN** the tab's button row SHALL contain exactly: an Add button, a Remove-Selected button, and a Clear-All button — and SHALL NOT contain any control whose text or role is Save or Load
