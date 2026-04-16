## Why

After clicking a plate entry in the plate list and then deleting it, the Review page loses its keyboard-shortcut context: pressing an arrow/cursor key no longer steps to the next frame and can instead start video playback that the user cannot stop. The plate list uses dynamically-rebuilt `QPushButton` chips; clicking one transfers focus out of the `ReviewPage` subtree, and the delete flow then destroys the focused chip without restoring focus. The Review page's frame-stepping shortcuts use `Qt.WidgetWithChildrenShortcut` context, so once focus escapes the subtree the arrow keys dispatch to whichever widget currently owns focus — including the `QMediaPlayer`-backed view that maps arrow keys to transport actions. Deleting from the video canvas works correctly because that path explicitly calls `_forward_focus()` to return focus to the Review page.

## What Changes

- Make plate-chip buttons non-focus-stealing (`Qt.NoFocus`) so that clicking a chip never removes keyboard focus from the Review page.
- After any plate-chip interaction (click, list refresh, delete), ensure the Review page retains keyboard focus by calling the same focus-restoration path used by the video-canvas interaction (`_forward_focus`-equivalent on the Review page).
- Eliminate the asymmetry between "delete via canvas click" and "delete via plate-list click" so both paths leave focus, shortcut context, and playback state identical.
- Add regression tests covering: (a) arrow keys continue to step frames after a list-based delete, (b) playback does not start spontaneously after a list-based delete, (c) delete key still works from both entry points.

## Capabilities

### New Capabilities
<!-- None — this is a behavior fix on an existing capability. -->

### Modified Capabilities
- `plate-overlay-ui`: Add requirements guaranteeing that plate-list (chip) interactions preserve Review-page keyboard focus so frame-navigation and playback shortcuts keep working identically to the canvas interaction path.

## Impact

- Code:
  - `src/trailvideocut/ui/review_page.py` — chip creation in `_refresh_plate_list`, handler `_on_plate_chip_clicked`, and delete-from-list flow. Likely extract/reuse a small `_restore_keyboard_focus()` helper analogous to `PlateOverlayWidget._forward_focus`.
- Tests:
  - `tests/test_plate_overlay.py` and/or `tests/test_plate_frame_actions.py` — add focus/shortcut regression tests using `QTest` for the list-click → delete → arrow-key path.
- User-visible behavior: fixes the bug with no change to intentional UI flows. No breaking changes, no API changes, no schema changes.
- Dependencies: none (PySide6 only).
- Risk: low — change is scoped to focus policy and focus restoration calls in one widget.
