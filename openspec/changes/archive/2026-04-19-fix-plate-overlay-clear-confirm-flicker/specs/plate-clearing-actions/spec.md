## MODIFIED Requirements

### Requirement: Clear all plates in selected clip
The system SHALL provide a "Clear Clip Plates" button that deletes all plate boxes (both auto-detected and manual) for the currently selected clip. The operation SHALL require user confirmation via a modal dialog before proceeding. After clearing, plate data for the clip SHALL be removed from memory and persisted to disk. Regardless of the user's Yes/No choice, when the confirmation dialog closes the plate overlay SHALL be visible and SHALL accurately reflect the clip's in-memory plate data (which is unchanged on No and updated on Yes). The system SHALL NOT rely on the overlay's reactive `unexpectedly_hidden` self-restoration path to guarantee post-dialog visibility for this call-site; restoration SHALL be performed explicitly by the Review page after the modal returns.

#### Scenario: User clears clip plates with confirmation
- **WHEN** the user clicks "Clear Clip Plates" and confirms in the dialog
- **THEN** the system removes all plate data for the selected clip, persists the updated data, refreshes the overlay to show no boxes for that clip, and updates the plate list widget

#### Scenario: User cancels clip clearing
- **WHEN** the user clicks "Clear Clip Plates" and cancels in the confirmation dialog (clicks "No" or dismisses)
- **THEN** no plate data is modified, the plate overlay remains visible (subject to the "Show Plates" checkbox state), and the overlay displays exactly the same set of plate boxes for the selected clip and current frame as it did immediately before the dialog was opened

#### Scenario: Overlay hidden by window manager during confirmation dialog
- **WHEN** the user clicks "Clear Clip Plates", the window manager hides the plate overlay while the confirmation dialog is open, and the user then clicks "No" (or "Yes")
- **THEN** after the dialog closes, the plate overlay SHALL be re-shown by the Review page (subject to the "Show Plates" checkbox), its `clip_data` SHALL match the post-choice in-memory plate data for the selected clip, and the user SHALL NOT need to navigate away from the Review page and back to see the overlay boxes again

#### Scenario: Clear clip plates when it's the only clip with data
- **WHEN** the user clears clip plates and no other clips have plate data
- **THEN** the system removes the clip's plate data, deletes the sidecar file if no plate data remains, and disables plate UI controls (same behavior as "Clear Saved Plates")

#### Scenario: Button disabled state
- **WHEN** no clip is selected, or the selected clip has no plate data
- **THEN** the "Clear Clip Plates" button SHALL be disabled
