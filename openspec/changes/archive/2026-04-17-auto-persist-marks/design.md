## Context

`SetupPage` keeps a `list[float]` of must-include marks and two buttons (`Save Marks`, `Load Marks`) that round-trip a raw JSON array via `QFileDialog`. By contrast, the sibling exclusion-ranges feature already has auto-persistence: `video/exclusions.py` exposes `save_exclusions` / `load_exclusions` against a versioned sidecar `{video_stem}.exclusions.json`, and `SetupPage._browse_video` + `_on_exclusions_changed` wire that into open-time auto-load and edit-time auto-save. The two features diverged only because the exclusion sidecar was added later and codified a pattern that marks pre-date. Users experience this as "marks keep getting lost while exclusions are sticky."

The marks sidecar format on disk today is a bare JSON list of seconds (e.g. `[1.2, 3.4]`). Some users already have these files next to their videos.

The Setup page uses `QShortcut` bindings we want to surface in the README (`A` add mark, `D` delete selected, `I`/`O` exclusion start/end, `Space` play/pause, arrow keys for stepping). None of this is documented today except in source.

## Goals / Non-Goals

**Goals:**
- Bring marks persistence to behavioural parity with exclusion ranges: auto-save on every mutation, auto-load on video open, no user-visible I/O dialogs.
- Adopt the same sidecar schema shape (version + filename binding + payload) so future readers of either file use the same mental model.
- Delete the now-useless Save/Load buttons (they would just duplicate automatic behaviour and invite confused users).
- Document the Setup-page keyboard shortcuts — especially the marks ones — in README so new users discover them.
- Preserve backward compatibility with existing bare-array sidecars for at least one release.

**Non-Goals:**
- Changing what a "mark" means, how it participates in clip selection, or how the CLI accepts `-i` timestamps.
- Adding UI for re-ordering, editing individual mark times by typing, or labelling marks.
- A general "project file" that bundles marks + exclusions + plate data into one document — each feature keeps its own sidecar.
- Undo/redo for mark operations.
- Migrating already-saved legacy sidecars in a batch tool; we simply accept them on load and the next write upgrades the schema.

## Decisions

### Decision: Mirror `video/exclusions.py` rather than extend `plate/storage.py`

Marks and exclusions are both "a list of floats (or pairs) sidecarred next to a video." `exclusions.py` is the cleaner, newer reference implementation — flat module, dataclass-free helpers, `logging.warning` on every recoverable failure, no PySide6 imports. Plate storage is coupled to `ClipPlateData` and has a richer schema that would be overkill here. We copy the exclusions shape file-for-file: `get_marks_path`, `save_marks`, `load_marks`, `delete_marks`, same version/filename guards, same "missing file is silent, corrupt file is logged + empty list" error contract.

Alternatives considered:
- **Inline save/load inside `setup_page.py`** (today's approach): keeps file-count low but duplicates validation logic per call-site and blocks unit testing without a Qt harness.
- **One shared `video/sidecars.py` for both marks and exclusions**: overfits; the two payloads are different shapes (`[float]` vs `[{start, end}]`) and the premature abstraction would hide that each will evolve separately.

### Decision: Versioned schema `{"version": 1, "video_filename": str, "marks": [float, ...]}`

Matches exclusions.py verbatim. The `video_filename` binding catches the common footgun of a sidecar following a renamed video. The `version` field is free insurance — we've already needed it once in this repo (see `plate/storage.py`'s version-check discard path).

### Decision: Loader accepts legacy bare-array sidecars

`load_marks` first parses JSON, then branches: `list` → treat as legacy (all entries must be numeric, else discard and log), `dict` → require `version` in supported set and `video_filename` match. This costs ~10 lines and avoids silently dropping users' existing marks when they upgrade. Next mutation rewrites to the new schema, so legacy sidecars auto-upgrade after one edit.

Rollback is trivial: the new format is a strict superset of information (list-of-floats fits inside the `marks` key), so we can revert code without corrupting on-disk data. Old sidecars still parse; new sidecars would simply fail the old loader's `isinstance(data, list)` check and be treated as empty — acceptable for a rollback window since the user can still re-add marks.

### Decision: Auto-save is best-effort and silent on success, logged on failure

Same semantics as `save_exclusions`: catch `PermissionError` and `OSError`, log a warning, never raise into the UI thread. A QMessageBox on every permissions failure would be noisy and misleading (the user's intent was "add a mark", not "save a file"). The failure case we optimise for is "user on a read-only share" — we want the mark to live in memory for the session and only the sidecar write to be skipped.

### Decision: Remove Save/Load buttons outright rather than hide them behind a debug flag

They become actively misleading once auto-persistence ships — a "Save Marks" button next to an auto-saved state implies the auto-save is unreliable. Clean removal.

### Decision: README gains a `Keyboard shortcuts` subsection under GUI

A flat Markdown table keyed by key → action. Covers Setup-page bindings only (Review and Export have their own bindings; out of scope for this change and already partly documented inline). Cross-references the Marks and Excluded tabs.

## Risks / Trade-offs

- **Users rely on the Load Marks dialog to import marks from a different video's sidecar** → Mitigation: document the convention (`mv other.marks.json thisvideo.marks.json`) in the README's Marks section. This is niche enough not to justify keeping the dialog.
- **Auto-save on every keystroke-triggered add could write the sidecar hundreds of times during rapid `A` presses** → Mitigation: acceptable for the observed working set (marks typically <50). `save_marks` is synchronous `write_text` of a small JSON blob, and exclusions already do the same with no complaints. Revisit only if profiling flags it.
- **Legacy bare-array loader adds a branch that must be covered by tests forever** → Mitigation: one scenario in the spec pins the behaviour; a follow-up change in a future release can drop legacy support after a deprecation note in release notes.
- **Permission-denied write silently drops the save** → Mitigation: consistent with exclusions; surface via the existing logger sink. Users on locked-down shares already see this pattern for exclusions.

## Migration Plan

1. Ship the new loader (accepts both formats) and new UI (no buttons) in the same release. No data migration step needed — existing sidecars are read as-is and rewritten to v1 format on the first mutation.
2. No rollback script needed. A revert reintroduces the buttons; on-disk v1 sidecars would be ignored by the old loader (the old code required `isinstance(data, list)`), so users would re-add marks in memory and old code would re-save as a bare array on Save-click. No data loss, one lost set of edits in the rollback window per video — acceptable.
3. Announce the change in the release notes with a one-liner: "Marks auto-save to a sidecar next to your video, like exclusion ranges — no more Save/Load buttons."
