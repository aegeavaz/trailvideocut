## 1. Write failing regression tests first (TDD)

- [x] 1.1 Add a minimal Qt test fixture in `tests/conftest.py` (or a new `tests/test_review_page_focus.py`) that supplies a single `QApplication` instance for the session, using `QApplication.instance() or QApplication([])` guarded by `QT_QPA_PLATFORM=offscreen`. Do NOT add `pytest-qt` as a dependency — use the bare Qt APIs already in use by the app.
- [x] 1.2 Write a failing test `test_plate_chips_are_not_focusable` that: instantiates `ReviewPage` (mock/stub its heavy collaborators if necessary so the widget can be built headlessly), injects a `ClipPlateData` with at least two `PlateBox`es on the current frame, calls `_refresh_plate_list()`, enumerates the `QPushButton` chip widgets in `self._plate_chips_layout`, and asserts every chip's `focusPolicy() == Qt.NoFocus`. This test MUST fail on the current codebase because `QPushButton` defaults to `Qt.StrongFocus`.
- [x] 1.3 Realized as `test_on_plate_chip_clicked_restores_focus_to_page` — forces a decoy widget to own focus, invokes the handler, asserts `review_page.hasFocus()` becomes True and no chip owns focus. (Renamed from the original plan because `QTest.mouseClick` does not realistically transfer focus under `QT_QPA_PLATFORM=offscreen`; the rewritten test forces the buggy pre-state deterministically via `decoy.setFocus()`.)
- [x] 1.4 Realized as `test_delete_via_chip_then_arrow_does_not_leave_hold_step_active` — invokes the handlers directly (`_on_plate_chip_clicked`, `_on_delete_key`, `_on_step_forward_pressed`, then `keyReleaseEvent` with a synthesized `QKeyEvent`). QShortcut dispatch is unreliable in offscreen, so handlers are called directly; assertions cover: the selected plate is removed, `_hold_step_direction` is 1 after press, 0 after release, and both hold-step timers are inactive.
- [x] 1.5 Replaced by `test_refresh_plate_list_does_not_steal_focus` (negative guard: passive scroll-driven refresh must NOT restore focus) and `test_canvas_forward_focus_lands_inside_review_page_subtree` (regression guard for the existing canvas path, asserting focus lands on ReviewPage or any descendant via `isAncestorOf`). The original literal diff-based equivalence test was too coupled to offscreen-Qt focus quirks; the two replacements codify the same invariants more deterministically.
- [x] 1.6 Confirmed failing state before fix: tests 1, 2 failed; tests 3, 4 (after rewrite) were still deterministic enough to validate the fix via the `_restore_keyboard_focus` method not existing on the handler path.

## 2. Implement the fix

- [x] 2.1 Added `ReviewPage._restore_keyboard_focus()` mirroring `PlateOverlayWidget._forward_focus`. Also added `self.setFocusPolicy(Qt.StrongFocus)` in `ReviewPage.__init__` — a prerequisite for `setFocus()` to actually land focus on the page; without it, both the new helper and the existing `_forward_focus` target are silently no-op under base-QWidget defaults.
- [x] 2.2 Added `chip.setFocusPolicy(Qt.NoFocus)` at the chip creation site.
- [x] 2.3 `_on_plate_chip_clicked` now calls `self._restore_keyboard_focus()` after `_refresh_plate_list()`. Helper is NOT invoked from `_refresh_plate_list` itself, preserving the invariant that passive scroll-driven refreshes do not steal focus.
- [x] 2.4 Verified — the 11 other `QPushButton(...)` hits in `review_page.py` are persistent named buttons (Back, Preview, Export, Detect Plates, Add Plate, Clear variants, Preview Blur, Cancel). None are destroyed/recreated like the dynamic chips, so the bug mechanism doesn't apply to them.
- [x] 2.5 All 5 focus regression tests now pass.

## 3. Guard against regressions and verify end-to-end behavior

- [x] 3.1 Full suite: 311 passed, 11 skipped (GPU-only, unaffected). No regressions.
- [ ] 3.2 Manual verification on the running app — **requires the user to run interactively**: launch the app, load a clip with detected plates, navigate to a frame that has at least two plates, then sequentially verify:
  - (a) arrow keys step frames before any plate interaction;
  - (b) click plate on canvas → press Delete → press Right-arrow: frame advances by one, no runaway stepping;
  - (c) click plate chip → press Delete → press Right-arrow: frame advances by one, no runaway stepping — THIS is the primary bug repro;
  - (d) click plate chip → press Space: play toggles correctly (shortcut context still intact);
  - (e) click plate chip without deleting → press Right-arrow: frame advances by one.
- [ ] 3.3 Manual canvas-path spot-check — **requires the user to run interactively**: repeat the user's original canvas-click-delete-arrow flow and confirm end state is observably identical between chip and canvas paths.
- [x] 3.4 `openspec validate fix-plate-list-focus-frame-nav` reports the change as valid.

## 4. Documentation and commit hygiene

- [ ] 4.1 Commit message — deferred to the user-triggered commit step.
- [x] 4.2 Comments in `review_page.py` are minimal: one sentence above `_restore_keyboard_focus` explaining the invariant, and three lines above `setFocusPolicy(Qt.StrongFocus)` in `__init__` explaining why the page needs to accept focus. No other comments added.
- [x] 4.3 Unrelated code paths untouched.
