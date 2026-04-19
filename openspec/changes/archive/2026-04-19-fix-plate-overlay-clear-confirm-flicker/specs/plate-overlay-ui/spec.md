## ADDED Requirements

### Requirement: Overlay survives Review-page modal dialogs
Because the plate overlay is a top-level transparent window, a modal `QMessageBox` (or equivalent modal dialog) shown by the Review page may cause the window manager to hide the overlay for the duration of the modal. After ANY such modal shown by the Review page closes, the overlay SHALL be restored to a state consistent with the current in-memory plate data and the "Show Plates" checkbox: if the checkbox is checked and `_plate_data` is non-empty, the overlay SHALL be visible, pointed at the currently-selected clip's data (or `None` if the selected clip has no data), and positioned correctly over the video display. The user SHALL NOT need to leave the Review page and return to force the overlay to re-render. This restoration SHALL be performed explicitly at each modal call-site rather than relying solely on the overlay's reactive `unexpectedly_hidden` signal, because that reactive path is racy with long-running modal event loops.

#### Scenario: Confirmation dialog (Clear Clip Plates) dismissed
- **WHEN** the user invokes a confirmation `QMessageBox` (e.g., "Clear Clip Plates") while the overlay is visible, and dismisses the dialog (Yes or No), and the window manager had hidden the overlay for the duration of the modal
- **THEN** after the dialog closes the overlay SHALL be re-shown (subject to the "Show Plates" checkbox and the non-emptiness of `_plate_data` after the user's choice has been applied) without requiring the user to navigate away from the Review page

#### Scenario: Informational dialog (`QMessageBox.warning` / `QMessageBox.critical`) during plate workflows
- **WHEN** the Review page shows an informational dialog during plate-related workflows (model download failure, plate-detection error, single-frame read error) while plate data exists in memory and the overlay is (or was) visible
- **THEN** after the user dismisses the dialog the overlay SHALL be re-shown consistent with `_plate_data` and the "Show Plates" checkbox — the user SHALL NOT be left with a stale, hidden overlay after acknowledging the error

#### Scenario: Overlay never had data
- **WHEN** a Review-page modal is shown while `_plate_data` is empty (e.g., "No video or clips available" warning before any detection has run)
- **THEN** the restoration routine SHALL be a no-op — it SHALL NOT force the overlay visible when there is nothing to show

#### Scenario: Show-plates checkbox is unchecked
- **WHEN** a Review-page modal is dismissed while the user has explicitly turned off "Show Plates"
- **THEN** the overlay SHALL remain hidden after restoration — the user's explicit visibility choice SHALL override the auto-restore behavior
