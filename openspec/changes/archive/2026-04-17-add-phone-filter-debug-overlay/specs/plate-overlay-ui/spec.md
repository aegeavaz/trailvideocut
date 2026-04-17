## ADDED Requirements

### Requirement: Overlay accepts and renders phone-zone debug geometry

`PlateOverlayWidget` SHALL expose a public API to set and clear per-frame phone-zone geometry (`set_phone_zones(zones)` / `clear_phone_zones()`), and SHALL render those zones during its `paintEvent` as non-interactive debug rectangles distinct from plate boxes and blur-preview tiles. The rendering pass SHALL be drawn *before* plate boxes and *after* the background transparency fill.

#### Scenario: set_phone_zones with active zones
- **WHEN** the Review page calls `set_phone_zones([(nx, ny, nw, nh), ...])` for the current frame
- **THEN** on the next paint the overlay SHALL draw one dashed, translucent-filled rectangle per zone at the correct video-relative position, using the same coordinate transform as plate boxes

#### Scenario: set_phone_zones with empty list
- **WHEN** `set_phone_zones([])` is called
- **THEN** the overlay SHALL draw no phone-zone rectangles on the next paint

#### Scenario: clear_phone_zones
- **WHEN** `clear_phone_zones()` is called while zones are currently drawn
- **THEN** the overlay SHALL remove all zones from its next paint and SHALL NOT re-introduce them until `set_phone_zones(...)` is called again

#### Scenario: Plate box layered above zone
- **WHEN** a plate box and a phone zone overlap on the same frame
- **THEN** the plate box SHALL be fully visible on top of the zone's translucent fill and dashed border

### Requirement: Phone-zone rendering is orthogonal to plate-box and blur-tile rendering

Setting or clearing phone zones SHALL NOT alter the overlay's plate-box list, selection state, blur-preview tiles, or any other interactive state.

#### Scenario: Set zones while a plate is selected
- **WHEN** a plate box is selected and `set_phone_zones(...)` is called with new zones for the current frame
- **THEN** the selection SHALL remain on the same plate box, resize handles SHALL remain drawn, and `selection_changed` SHALL NOT fire as a side effect

#### Scenario: Set zones while blur tiles are active
- **WHEN** blur-preview tiles are set on the overlay and `set_phone_zones(...)` is called
- **THEN** the blur tiles SHALL continue to render unchanged, and zones SHALL render underneath the blur tiles

### Requirement: Phone zones SHALL NOT participate in input handling

Phone-zone rectangles SHALL NOT be returned by any hit-test routine, SHALL NOT change cursor shape on hover, and SHALL NOT consume mouse or keyboard events. All existing input semantics for plate boxes SHALL behave as if the zones were not drawn.

#### Scenario: Hover over a zone with no plate beneath
- **WHEN** the mouse hovers over a phone-zone rectangle at a position where no plate box exists
- **THEN** the cursor SHALL NOT change to a resize / move / pointing-hand cursor because of the zone, and the cursor SHALL follow the existing rules (arrow cursor when not zoomed; open-hand cursor when zoomed in)

#### Scenario: Left-click on a zone with no plate beneath
- **WHEN** the user left-clicks inside a zone at a position where no plate box exists
- **THEN** the click SHALL trigger the existing "empty video space click" behavior (deselect current plate / start pan if zoomed) and the zone SHALL NOT become selected

#### Scenario: Right-click inside a zone
- **WHEN** the user right-clicks inside a zone on empty video space with no plate selected
- **THEN** the `add_plate_requested` signal SHALL fire with the normalized click coordinates exactly as it would without the zone present
