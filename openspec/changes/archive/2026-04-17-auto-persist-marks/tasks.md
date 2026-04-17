## 1. Marks data module (TDD)

- [x] 1.1 Create `tests/test_video_marks.py` with failing tests first, covering: `get_marks_path` derivation, round-trip save → load of a non-empty mark list, empty-list save writes `marks: []`, legacy bare-array load, legacy array with non-numeric entry discarded, missing sidecar returns `[]` silently, corrupt JSON discarded + warning, unknown version discarded + warning, filename mismatch discarded + warning, and `delete_marks` idempotent on missing file. Use `tmp_path` and `caplog`; no Qt, no network.
- [x] 1.2 Add `tests/test_video_marks.py::test_save_permission_denied` that writes under a read-only directory (`tmp_path` + `chmod 0o500`) and asserts `save_marks` returns without raising and logs a warning. Skip on Windows via `pytest.mark.skipif`.
- [x] 1.3 Create `src/trailvideocut/video/marks.py` with module docstring, `logger = logging.getLogger(__name__)`, `_VERSION = 1`, `_SUPPORTED_VERSIONS = {1}`, and `get_marks_path(video_path) -> Path` using `Path(video_path).with_suffix(".marks.json")`.
- [x] 1.4 Implement `save_marks(video_path, marks: list[float]) -> None`: sort ascending, serialise as `{"version": 1, "video_filename": Path(video_path).name, "marks": [...]}` with `json.dumps(..., indent=2)`, write UTF-8; catch `PermissionError` and `OSError` and log a warning naming the path.
- [x] 1.5 Implement `load_marks(video_path) -> list[float]`: return `[]` silently when the path does not exist. Read + `json.loads`; on `JSONDecodeError` or `OSError` log and return `[]`. Branch on `isinstance(raw, list)` for the legacy path: accept only if every entry is `int` or `float`, else log + return `[]`; sort and return the floats. Otherwise require `dict` with `version` in `_SUPPORTED_VERSIONS`, `video_filename == Path(video_path).name`, and `marks` being a `list` of numbers — every failure path logs a distinct warning and returns `[]`.
- [x] 1.6 Implement `delete_marks(video_path) -> None` using `Path.unlink(missing_ok=True)` with `OSError` logged (not raised).
- [x] 1.7 Run `pytest tests/test_video_marks.py -q` — all tests added in 1.1–1.2 pass.

## 2. Setup page integration

- [x] 2.1 In `src/trailvideocut/ui/setup_page.py`, remove the `btn_save_marks` and `btn_load_marks` widgets, their `clicked` connections, and the `_save_marks` / `_load_marks` methods. Drop the now-unused `import json`, `QFileDialog` (if only used here), and `QMessageBox` (if only used here).
- [x] 2.2 Add imports `from trailvideocut.video.marks import load_marks, save_marks` and introduce a private helper `self._persist_marks()` that calls `save_marks(Path(self._video_path.text().strip()), list(self._marks))` only when a video path is set.
- [x] 2.3 Call `self._persist_marks()` at the end of each of `_add_mark`, `_remove_mark`, and `_clear_marks` — after the list mutation and `_refresh_marks_ui()` return.
- [x] 2.4 Add a private `_auto_load_marks(video_path: Path)` mirroring `_auto_load_exclusions`: sets `self._marks = load_marks(video_path)`, clears `self._selected_mark_index`, disables `_btn_remove_mark`, and calls `self._refresh_marks_ui()`.
- [x] 2.5 In `_browse_video`, invoke `self._auto_load_marks(Path(path))` next to the existing `self._auto_load_exclusions(Path(path))` call.
- [x] 2.6 Add or update `tests/test_setup_page_marks.py` (a new file — reference `tests/` conventions) with `pytest-qt` coverage for: (a) opening a video with an existing sidecar populates chips; (b) opening a video with no sidecar leaves chips empty; (c) pressing `A` adds a mark and writes the sidecar; (d) pressing `D` on a selected mark removes it and writes the sidecar; (e) `Clear All` writes an empty-array sidecar. Use `tmp_path` videos (dummy .mp4 is fine — the test need not decode).
- [x] 2.7 Run the targeted suite: `pytest tests/test_setup_page_marks.py tests/test_video_marks.py -q`.

## 3. Documentation

- [x] 3.1 In `README.md`, under the `### GUI` section after step 3, add a `#### Keyboard shortcuts` subsection with a Markdown table listing Setup-page bindings: `Space` play/pause, `← / →` step back / forward one frame (auto-repeat while held), `↑ / ↓` jump forward / back, `Home / End` go to start / end, `A` add a must-include mark at the current frame, `D` remove the selected mark, `I / O` capture exclusion range start / end, `Esc` cancel a pending exclusion range.
- [x] 3.2 Under the same GUI section, add a short `#### Marks` paragraph that states: marks are must-include timestamps the clip selector always preserves; they auto-save to `{video_stem}.marks.json` next to the video (no Save button needed) and auto-load when the video is reopened; to reuse marks from another video, copy the sidecar and rename it to match the new video's stem.
- [x] 3.3 In the `## Features` bullet list, refine the existing `Must-include marks` line to mention the auto-persisted sidecar, matching the phrasing already used for the `Exclusion ranges` line.

## 4. Validation

- [x] 4.1 Run the full test suite: `pytest -q`. All existing tests pass and the new tests added in §1 and §2 pass.
- [x] 4.2 Smoke-test the GUI manually: launch `trailvideocut ui`, open a video, press `A` a few times, close the app, reopen the same video, and confirm the chips reappear. Then open a different video and confirm its marks (or absence of them) are independent.
- [x] 4.3 Run `openspec validate auto-persist-marks --strict` and confirm no errors.
