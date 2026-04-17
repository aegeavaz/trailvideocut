## ADDED Requirements

### Requirement: Render phone-filter debug zones on the video overlay

The system SHALL render the phone/device exclusion zones used by the plate detector as non-interactive debug rectangles on top of the video player for the currently displayed frame, using the same normalized-to-widget coordinate mapping used for plate boxes. Zones SHALL be drawn with a visually distinct dashed border and translucent fill so they cannot be mistaken for plate bounding boxes or blur-preview tiles.

#### Scenario: Frame with active phone zones
- **WHEN** the Review page displays a frame whose associated `ClipPlateData` contains one or more phone zones for that frame number
- **THEN** each zone SHALL be drawn at the correct position and size over the video, using a dashed border and translucent fill in a color distinct from plate-box colors, scaled to match the current video display area

#### Scenario: Frame with no phone zones
- **WHEN** the Review page displays a frame that has no phone-zone entry in `ClipPlateData`
- **THEN** no phone-zone rectangles SHALL be drawn, regardless of the "Show Phone Filter" toggle state

#### Scenario: Video widget resized while zones are visible
- **WHEN** the user resizes the application window while phone zones are visible
- **THEN** each phone-zone rectangle SHALL reposition and rescale to match the new video display area using the same transform applied to plate boxes

### Requirement: Phone-filter debug zones SHALL be non-interactive

Phone-zone rectangles SHALL NOT respond to mouse input. They SHALL NOT be selectable, movable, resizable, or deletable, and SHALL NOT participate in plate-box hit-testing, right-click add-plate, or keyboard shortcuts.

#### Scenario: Click inside a phone zone that does not overlap a plate box
- **WHEN** the user left-clicks inside a drawn phone-zone rectangle and no plate box intersects that point
- **THEN** the click SHALL behave exactly as a click on empty video space (deselect current plate if any; start pan if zoomed in) and no zone SHALL become "selected"

#### Scenario: Click inside a phone zone that overlaps a plate box
- **WHEN** the user left-clicks inside a region where a phone zone and a plate box overlap
- **THEN** the existing plate-box hit-testing rules SHALL apply unchanged (topmost / smallest-area box wins) as if the phone zone were not drawn

#### Scenario: Right-click inside a phone zone with no plate selected
- **WHEN** the user right-clicks inside a phone-zone rectangle on empty video space (no plate box at that point, no plate selected)
- **THEN** the add-plate-requested action SHALL fire exactly as it would if the zone were not drawn

#### Scenario: Delete key while zones are visible
- **WHEN** phone zones are visible and the user presses the Delete or Backspace key
- **THEN** only plate-box deletion semantics SHALL apply; no phone zone SHALL be removable from the UI

### Requirement: Dedicated "Show Phone Filter" visibility toggle

The Review page SHALL provide a "Show Phone Filter" checkbox in the plate-controls settings row. The checkbox SHALL control whether phone-zone rectangles are drawn on the overlay, independently of the "Show Plates" checkbox.

#### Scenario: Toggle turns rendering on
- **WHEN** the user checks "Show Phone Filter" with an active clip whose current frame has phone zones
- **THEN** the phone-zone rectangles SHALL appear on the overlay on the next paint without affecting plate-box visibility

#### Scenario: Toggle turns rendering off
- **WHEN** the user unchecks "Show Phone Filter" while zones are visible
- **THEN** the phone-zone rectangles SHALL disappear on the next paint and plate-box visibility SHALL remain unchanged

#### Scenario: Independence from plate visibility
- **WHEN** "Show Plates" is unchecked and "Show Phone Filter" is checked, and the current frame has both plate detections and phone zones
- **THEN** only the phone-zone rectangles SHALL be drawn; no plate boxes SHALL be drawn

### Requirement: Toggle availability tracks filter state

The "Show Phone Filter" checkbox SHALL be enabled only when the "Exclude Phone" checkbox is checked AND the currently selected clip's plate data contains at least one frame with phone zones. Otherwise the checkbox SHALL be disabled and forced to unchecked.

#### Scenario: Exclude Phone is unchecked
- **WHEN** the "Exclude Phone" checkbox is unchecked
- **THEN** the "Show Phone Filter" checkbox SHALL be disabled, its state SHALL be unchecked, and no phone zones SHALL be drawn even if zones exist in memory

#### Scenario: Exclude Phone checked but no zones recorded yet
- **WHEN** the "Exclude Phone" checkbox is checked but the selected clip has no phone-zone data (e.g., detection has not yet run)
- **THEN** the "Show Phone Filter" checkbox SHALL be disabled and unchecked

#### Scenario: Both conditions satisfied
- **WHEN** the "Exclude Phone" checkbox is checked and the selected clip has at least one frame with phone zones
- **THEN** the "Show Phone Filter" checkbox SHALL be enabled and user-toggleable

### Requirement: Phone zones persist in the plates sidecar

Phone zones SHALL be serialized into the same `.plates.json` sidecar file as plate detections so they survive app restarts. The sidecar schema version SHALL be bumped (v2) to distinguish it from earlier files. Older v1 sidecars SHALL still load — their plate detections are preserved and the reconstructed `ClipPlateData.phone_zones` is empty. Exported artifacts (DaVinci Lua, blur export) SHALL continue to ignore the zones — persistence is strictly inside the sidecar.

#### Scenario: Save plates with zones to sidecar
- **WHEN** plate data with non-empty `phone_zones` is saved
- **THEN** the sidecar JSON SHALL carry `"version": 2` and a per-clip `"phone_zones"` object mapping frame-number strings to arrays of `[x, y, w, h]` normalized tuples

#### Scenario: Save plates without zones
- **WHEN** plate data is saved for a clip whose `phone_zones` map is empty
- **THEN** the per-clip JSON SHALL NOT include the `"phone_zones"` key (keep files compact)

#### Scenario: Round-trip preserves zones
- **WHEN** plate data with zones is saved and then reloaded from the sidecar
- **THEN** the reloaded `ClipPlateData.phone_zones` SHALL equal the original map (same frame keys, same tuples)

#### Scenario: v1 sidecar backward compatibility
- **WHEN** a legacy v1 sidecar (no `phone_zones` field) is loaded
- **THEN** `load_plates` SHALL return `ClipPlateData` objects with intact `detections` and empty `phone_zones`, and the "Show Phone Filter" checkbox SHALL be disabled until detection is re-run
