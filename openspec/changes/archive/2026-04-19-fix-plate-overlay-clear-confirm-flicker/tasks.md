## 1. Write failing regression tests (TDD — RED)

- [x] 1.1 Identify the existing Qt test fixture pattern under `tests/` (qapp fixture, ReviewPage construction helpers) and reuse it; if none exists, add a minimal `pytest-qt` fixture that spins up `QApplication` and builds a `ReviewPage` with seeded `_plate_data` for one clip, a selected clip, and `_chk_show_plates` checked
- [x] 1.2 Add test `test_clear_clip_plates_cancel_keeps_overlay_visible` that monkeypatches `QMessageBox.question` to return `QMessageBox.No`, calls `ReviewPage._on_clear_clip_plates()`, and asserts: `_plate_data[selected]` unchanged (identity + contents), `_plate_overlay.isVisible() is True`, `_plate_overlay._clip_data is _plate_data[selected]`, and `_plate_overlay._current_frame` equals the pre-call value
- [x] 1.3 Add test `test_clear_clip_plates_confirm_clears_data_and_rehomes_overlay` that monkeypatches `QMessageBox.question` to return `QMessageBox.Yes` with a single clip having plate data, then asserts `_plate_data == {}`, `_plate_overlay._clip_data is None`, `_plate_overlay.isVisible() is False`, and that plate-related buttons are disabled (matches existing "all clips now empty" branch)
- [x] 1.4 Add test `test_clear_clip_plates_confirm_with_other_clips_keeps_overlay_synced` — two clips have plate data, user confirms clear on one; assert the other clip's data is untouched and the overlay is synced to the currently selected clip (which may now have `None` clip_data but is still visible per show-plates checkbox)
- [x] 1.5 Run `pytest tests/` and confirm 1.2 fails (overlay not restored on No) while 1.3 and 1.4 pass against current code (happy path already self-heals). If 1.3/1.4 also fail, note the additional defect in the apply phase
  - Result: 1.2 FAILED (cancel path, the primary bug), 1.3 PASSED (only-clip Yes branch explicitly sets `setVisible(False)`), 1.4 FAILED (confirm-with-other-clips: `_sync_overlay_to_current_clip` in the "some data remains" branch does NOT restore visibility). Task 3.2 will append `_restore_overlay_for_current_clip()` to that branch.

## 2. Implement overlay restoration helper

- [x] 2.1 In `src/trailvideocut/ui/review_page.py`, add a private method `_restore_overlay_for_current_clip(self)` that: (a) early-returns if `not self._plate_data` (no data to show), (b) sets `self._plate_overlay.setVisible(self._chk_show_plates.isChecked())`, (c) calls `self._sync_overlay_to_current_clip()`, (d) calls `self._plate_overlay.raise_()` to defeat residual modal z-order
- [x] 2.2 Leave the existing `_restore_overlay` method (`review_page.py:1247`) untouched — it remains the reactive handler for `unexpectedly_hidden` from non-Review-page sources

## 3. Wire the helper into the cancel path of `_on_clear_clip_plates`

- [x] 3.1 In `_on_clear_clip_plates` (`review_page.py:1627`), after `QMessageBox.question(...)` returns, if `reply != QMessageBox.Yes` call `self._restore_overlay_for_current_clip()` *before* the early `return`
- [x] 3.2 On the Yes path, verify that existing branches already reach a correct overlay state: the "no plate data left" branch calls `set_clip_data(None) + setVisible(False)` and the "some data remains" branch calls `_sync_overlay_to_current_clip()`; if either path is observed to leave the overlay hidden when it should be visible (per failing tests from 1.3/1.4), append a call to `self._restore_overlay_for_current_clip()` at the end of the Yes branch for the "some data remains" case only
  - Result: as predicted in 1.5, the "some data remains" branch was replaced: `self._sync_overlay_to_current_clip()` → `self._restore_overlay_for_current_clip()` (the helper calls `_sync_overlay_to_current_clip()` itself, so no behavior lost). The "no plate data left" branch is unchanged — it still explicitly hides the overlay, which is correct.
- [x] 3.3 Audit for any other confirmation-`QMessageBox` call-sites on the Review page (`review_page.py` lines ~909, ~978, ~1113, ~1580) that operate with the overlay visible; if any can leave the overlay hidden after a cancel, add a call to `self._restore_overlay_for_current_clip()` immediately after the modal returns. Document any call-sites deliberately not updated (e.g., dialogs shown while the overlay is already intentionally hidden).
  - Audit result and resolution — `QMessageBox` call-sites in `review_page.py`:
    - **909** `_on_detect_plates` `QMessageBox.warning` (no clips/video): overlay has no data in this state, so nothing to restore. **No change needed** — `_restore_overlay_for_current_clip()` would be a no-op here anyway (early-returns when `_plate_data` is empty).
    - **978** `_on_download_error` `QMessageBox.critical`: **fixed** — added `self._restore_overlay_for_current_clip()` after the modal. The WM-hide mechanism is identical to the Clear Clip Plates case, so the user could hit the same phantom-hidden overlay after dismissing a download error if prior plate data exists.
    - **1113** `_on_plate_error` `QMessageBox.critical` (detection worker error): **fixed** — same rationale as 978.
    - **1595** `_run_single_frame_detection` `QMessageBox.warning` (frame-read failure): **fixed** — added before the existing early `return`. Frame-detect implies plate data already exists for the clip, so the overlay is almost certainly visible at this point.
    - **1648** `_on_clear_clip_plates` `QMessageBox.question`: **fixed** (tasks 3.1, 3.2).
    Regression tests for 978/1113/1595 are not added in this change (the helper is deterministic, gated on `_plate_data` non-empty, and the test pattern for modal call-sites is already established by the Clear Clip Plates tests); if flicker is observed at these sites a follow-up can add parameterized tests.

## 4. Verify

- [x] 4.1 Run `pytest tests/` and confirm all tests in section 1 pass
  - Result: 3/3 passed.
- [x] 4.2 Run the full existing test suite and confirm no regressions
  - Result: 486 passed, 11 skipped, 0 failed.
- [x] 4.3 Manual verification on the actual desktop build: load a clip with detected plates, click "Clear Clip Plates", click "No" in the confirmation — overlay remains showing the same boxes without navigating away; then repeat and click "Yes" — overlay updates to empty/hidden per the existing branch
  - Verified by user in a real desktop session — behaviour confirmed working.
- [x] 4.4 Manual verification on Windows specifically (if available) to ensure the owner-window path does not regress: the overlay SHALL NOT end up above unrelated top-level windows after restoration
  - Verified by user — owner-window path unchanged, no regression.
