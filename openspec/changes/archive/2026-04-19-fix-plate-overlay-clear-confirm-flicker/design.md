## Context

The plate overlay (`PlateOverlayWidget`, `src/trailvideocut/ui/plate_overlay.py`) is a **separate top-level, frameless, transparent window** — not a child of the video player. Because it has its own native window handle, the window manager is free to hide it when another top-level window (such as a modal `QMessageBox`) takes activation. On Windows the `showEvent` attempts to reparent the overlay via `SetWindowLongPtrW(GWL_HWNDPARENT, owner_hwnd)` to keep it above the main window only, but this owner-window dance does not fully insulate the overlay from modal dialogs on every Windows shell configuration, and on other platforms there is no such insulation at all.

The overlay already emits an `unexpectedly_hidden` signal (see `plate_overlay.py:87–90`) when a non-programmatic `hideEvent` fires, and the Review page listens (`review_page.py:146–147`, handler at `review_page.py:1242`). The handler schedules `_restore_overlay` via `QTimer.singleShot(0, …)`, which calls `show()` + `_position_overlay()` + `raise_()`.

The empirical bug: when the user clicks **Clear Clip Plates** and the confirmation `QMessageBox.question(...)` appears (`_on_clear_clip_plates`, `review_page.py:1627`), the overlay disappears and is not restored if the user answers **No**. On the happy path ("Yes") the overlay is already expected to reflect the cleared state, so the defect is only user-visible on cancel. The user must navigate away from the Review page and back before the overlay starts showing plates again.

There are two plausible failure modes for the existing restoration path:
1. The `QTimer.singleShot(0, …)` fires *while the modal is running*, so `_restore_overlay` calls `show()`/`raise_()`, but the modal immediately reactivates and the overlay is hidden again — leaving the final state hidden.
2. The `hideEvent` fires with `_hiding_programmatically == False`, but in some Qt/shell combinations the timer callback does not run at all during the modal loop, or the overlay's `isVisible()` state after the modal is a stale `False` that no subsequent event corrects.

Either way, the current mechanism is *reactive* (wait for the WM to hide, then heal). It is fragile around intentional modal dialogs we control, because the Review page already knows a dialog is about to open.

## Goals / Non-Goals

**Goals:**
- After the confirmation dialog in `_on_clear_clip_plates` closes, the plate overlay SHALL be visible and SHALL display exactly the plate data that was visible before the dialog opened — regardless of the user's Yes/No choice, and regardless of whether the WM hid the overlay during the modal.
- The fix SHALL be deterministic at the call-site, not reliant on the reactive `unexpectedly_hidden` timer path.
- The change SHALL preserve existing behavior on the "Yes" path: overlay is updated to reflect the cleared clip data (either hidden with no data, or showing the new empty state for the remaining clip).
- The reactive `unexpectedly_hidden` → `_restore_overlay` path SHALL remain functional as a safety net for non-Review-page modal sources.

**Non-Goals:**
- Reparenting `PlateOverlayWidget` to become a child of the video player. That is a larger architectural change with transparency/compositing implications and is out of scope for this fix.
- Windows `SetWindowLongPtrW` ownership changes or any native-window work.
- Changing the behavior of `_on_clear_frame_plates` (no confirmation dialog; not affected).
- Changing the `QMessageBox` itself (e.g., switching to a non-modal inline prompt).

## Decisions

### Decision 1: Restore the overlay at the call-site, immediately after the modal returns

The Review page already knows, at `_on_clear_clip_plates`, exactly when a modal is about to open and close. The fix is to capture the overlay's intended visibility *before* the modal, and after the modal returns (and after any data mutation on "Yes"), re-establish the overlay state by explicitly calling `_sync_overlay_to_current_clip()` and re-applying visibility from the `_chk_show_plates` checkbox.

On the **No** path:
- Data is untouched.
- Re-sync the overlay: `self._plate_overlay.setVisible(self._chk_show_plates.isChecked())` then `self._sync_overlay_to_current_clip()`.
- This guarantees the overlay reflects the preserved `_plate_data[selected]` even if it was hidden by the WM during the modal.

On the **Yes** path:
- The existing branch already calls either `set_clip_data(None) + setVisible(False)` (when no clip data remains) or `_sync_overlay_to_current_clip()` (when some remains). Both implicitly re-establish the correct overlay state, so the Yes path already self-heals. We will audit to confirm, but no functional change is required there.

**Alternative considered: fix the `unexpectedly_hidden` handler.** We could make `_restore_overlay` more aggressive (e.g., defer restoration until after the modal loop exits using `QApplication.activeModalWidget()` polling). This was rejected because: (a) it introduces polling where a direct call-site fix is available; (b) the reactive path is symptom-driven and can race with further hide events emitted by the modal; (c) it doesn't simplify testing.

**Alternative considered: suppress `unexpectedly_hidden` during the modal.** We could set `_hiding_programmatically = True` around the modal call. This was rejected because it misrepresents intent — the WM *is* hiding the overlay unexpectedly; we just want to repair it afterwards. Lying in the flag would also disable the safety net for any hide that happens concurrently for an unrelated reason.

### Decision 2: Use a small helper for "restore overlay to current clip"

Introduce (or reuse) a private helper on `ReviewPage`, e.g., `_restore_overlay_for_current_clip()`, that:
- sets visibility from `_chk_show_plates.isChecked()`, gated on `_plate_data` being non-empty (matching existing `_restore_overlay` preconditions),
- calls `_sync_overlay_to_current_clip()`,
- calls `_plate_overlay.raise_()` to defeat any residual z-order from the modal.

This keeps the fix localized and makes the same helper usable if additional confirmation dialogs are added in the future. This helper is close to the existing `_restore_overlay` (`review_page.py:1247`); we can either extend it or add a thin wrapper that also invokes `_sync_overlay_to_current_clip`. Prefer a new helper (single responsibility: "re-show with current clip data") and leave `_restore_overlay` as the reactive-path handler.

### Decision 3: Add a regression test for the No path

A `pytest` + `pytest-qt` test SHALL:
1. Build a `ReviewPage` with plate data for one clip preloaded.
2. Patch `QMessageBox.question` to return `QMessageBox.No` (avoids modal in test).
3. Call `_on_clear_clip_plates()` directly.
4. Assert `self._plate_data[selected]` is unchanged.
5. Assert `self._plate_overlay.isVisible()` is `True` (given show-plates checked).
6. Assert `self._plate_overlay._clip_data` is the same object as `self._plate_data[selected]`.

And a parallel happy-path test that returns `QMessageBox.Yes` and asserts data is cleared and overlay state matches the existing "all-clips-now-empty" or "some-clips-remain" branch.

Patching `QMessageBox.question` is the correct isolation: the bug is not in Qt's modal loop itself, it's in the Review page's handling around it. The test verifies the call-site contract.

## Risks / Trade-offs

- [The WM may still hide the overlay briefly during the modal, causing a visible flicker even on the No path] → The explicit post-modal `setVisible(True) + raise_()` restores it deterministically. A one-frame flicker is acceptable; persistent hiding is not. If flicker becomes a complaint, Decision 1's alternative (reparent the overlay) is the follow-up.
- [`_sync_overlay_to_current_clip()` has side effects beyond visibility — refreshes chips, phone zones, frame buttons] → These side effects are already idempotent and correct for the current state; calling them on the No path is a no-op on data. Verified by reading `_sync_overlay_to_current_clip` (`review_page.py:1176`).
- [Future confirmation dialogs elsewhere in the Review page could reintroduce the bug] → Mitigated by the reusable helper; reviewers can enforce its use in PR review. This is not a hard enforcement mechanism.
- [Tests depending on `pytest-qt` may be flaky in headless CI] → The `tests/` folder already contains Qt-based tests; we reuse their fixtures. If no Qt fixture exists, we add one following the existing pattern.
