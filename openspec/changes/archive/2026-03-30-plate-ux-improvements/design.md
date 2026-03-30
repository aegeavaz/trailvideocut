## Context

The video frame viewer in `VideoPlayer` uses `QGraphicsView.fitInView()` followed by `QGraphicsView.scale()` to implement zoom. This always scales from the viewport center, so the user must pan after zooming to reach the area of interest. Standard image viewers (Photoshop, GIMP, map applications) zoom toward the mouse cursor.

For adding plates, `PlateOverlayWidget.find_nearest_prior_box()` searches only backward through frame numbers. When the user adds a plate on the first frame of a clip (or before any detection), it falls back to a hardcoded centered position, ignoring potentially useful detections on later frames and the user's cursor position.

## Goals / Non-Goals

**Goals:**
- Zoom toward/away from the mouse cursor position, keeping the point under the cursor visually stable
- When adding a plate, search forward (next frames) if no prior frame has a detection
- When no reference detection exists in any direction, place the new box at the mouse cursor position instead of a hardcoded center

**Non-Goals:**
- Smooth/animated zoom transitions (snap zoom is sufficient)
- Keyboard-only zoom support (existing +/- buttons are unaffected)
- Changing zoom behavior outside the review page (setup page keeps current behavior)

## Decisions

### 1. Cursor-centered zoom via scroll bar adjustment

After applying `fitInView()` + `scale()`, compute the offset needed so the scene point under the cursor remains at the same viewport position. Use `QGraphicsView.mapToScene()` before zoom and `mapFromScene()` after to calculate the pixel delta, then adjust the scroll bars accordingly.

**Alternative considered:** Using `QGraphicsView.setTransformationAnchor(AnchorUnderMouse)` — rejected because `fitInView()` resets the transform each time, making the anchor mode ineffective. Manual scroll bar adjustment after the transform gives full control.

### 2. Bidirectional reference search in `find_nearest_prior_box()`

Rename to `find_nearest_reference_box()` and extend the search: first look backward (existing behavior), then look forward if nothing found. The nearest frame in either direction wins, with backward preferred when equidistant.

This is a minimal change — the forward search is the same loop reversed.

### 3. Mouse-position fallback via `_widget_to_norm()`

When no reference box exists in any frame, convert the current mouse cursor position (relative to the overlay widget) to normalized coordinates using the existing `_widget_to_norm()` helper, and place the new box centered on that point. The overlay already tracks mouse position for hit-testing.

**Alternative considered:** Using `QCursor.pos()` with global-to-local mapping — rejected because the overlay already has `_widget_to_norm()` and receives mouse events directly, making global coordinate mapping unnecessary.

### 4. Pass cursor position from overlay to review page

The `add_plate_requested` signal (emitted on right-click) will carry the normalized cursor position as a `tuple[float, float]`. The `_on_add_plate()` method in `ReviewPage` will accept an optional position parameter and pass it through when no reference box is found.

For the "Add Plate" button (no mouse position on video), query `PlateOverlayWidget` for the last known mouse position or fall back to center.

## Risks / Trade-offs

- **[Zoom feel]** Scroll-bar-based cursor centering may feel slightly different from true matrix-transform zooming at extreme zoom levels. → Mitigation: clamp scroll bar values to valid range; the 1.0-5.0 zoom range is modest enough that this works well.
- **[Forward reference surprise]** A box cloned from a future frame might confuse users who expect only backward propagation. → Mitigation: this is the fallback path (only used when no prior frame has data), and the box is immediately editable. The alternative (centered box) is more confusing.
