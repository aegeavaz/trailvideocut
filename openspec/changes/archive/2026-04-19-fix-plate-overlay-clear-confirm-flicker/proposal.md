## Why

When the user clicks "Clear Clip Plates" the confirmation `QMessageBox` causes the plate overlay (a standalone top-level transparent window) to be hidden by the window manager. The overlay is not restored when the dialog closes, so after the user clicks "No" the plates remain visible on disk/in memory but invisible on the video — the user must leave the Review page and return to force a re-sync. This makes the "No" path feel destructive and breaks user trust in the overlay as a source of truth.

## What Changes

- The Review page SHALL guarantee that the plate overlay is restored to its pre-dialog state after **any** modal `QMessageBox` it shows (confirmation, warning, critical) closes, regardless of the user's choice or the modal's outcome.
- The Review page SHALL re-show and re-sync the overlay when the "Clear Clip Plates" confirmation returns `No` (or the dialog is dismissed), so overlay contents match in-memory plate data.
- The Review page SHALL perform the same explicit restoration after the plate-related informational modals (`_on_download_error`, `_on_plate_error`, `_run_single_frame_detection` frame-read failure), which share the same WM-hide mechanism as the confirmation dialog.
- The plate overlay's `unexpectedly_hidden` self-restoration path SHALL remain active but SHALL no longer be the only mechanism responsible for restoring the overlay around Review-page modal dialogs; the Review page SHALL take explicit responsibility at each modal call-site.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `plate-clearing-actions`: Tighten the "User cancels clip clearing" scenario so it also guarantees the overlay continues to show the unchanged plate boxes after dismissal, and add a scenario covering overlay restoration around the confirmation dialog regardless of choice.
- `plate-overlay-ui`: Add a requirement that the plate overlay is restored to a state consistent with in-memory plate data and the "Show Plates" checkbox after ANY Review-page modal dialog closes. This broadens the restoration guarantee from the Clear Clip Plates confirmation to all modal dialogs shown by the Review page, because the WM-hide mechanism is identical at all modal call-sites.

## Impact

- Affected code:
  - `src/trailvideocut/ui/review_page.py` — new `_restore_overlay_for_current_clip()` helper; call-site additions in `_on_clear_clip_plates` (both branches), `_on_download_error`, `_on_plate_error`, and `_run_single_frame_detection` (frame-read failure branch).
  - `src/trailvideocut/ui/plate_overlay.py` — no functional change; existing `unexpectedly_hidden` signal and `setVisible` guard stay intact as a safety net.
- Affected tests: new unit/integration test(s) under `tests/` that exercise the "Clear Clip Plates → No" path with WM-hide simulation and assert the overlay is restored; the same pattern can be reused for the other modal call-sites if regressions are observed in the wild.
- No external API or data-format changes. No migration.
