## Context

The Review page (`src/trailvideocut/ui/review_page.py`) drives frame-by-frame plate review. Users navigate with arrow keys, toggle play with Space, and delete plates with Delete/Backspace. All of these are wired as `QShortcut`s on the `ReviewPage` with `Qt.WidgetWithChildrenShortcut` context (review_page.py:338-351). Arrow-key auto-repeat is intentionally disabled on the `QShortcut` itself; instead, the handlers call `self._player.start_step_hold(direction)` to start a timer-driven smooth step, and the matching `stop_step_hold()` is fired from `ReviewPage.keyReleaseEvent` (review_page.py:705-716).

Two UI surfaces let the user select a plate:

1. **Video canvas** — `PlateOverlayWidget` in `src/trailvideocut/ui/plate_overlay.py`. After every mouse interaction, `mousePressEvent` (and `_handle_right_click`) call `_forward_focus()` (plate_overlay.py:388-394), which activates the top-level window and calls `self._logical_parent.setFocus()` on the `ReviewPage`. The overlay itself has `Qt.NoFocus`, so focus never lives on the overlay.

2. **Plate "chips" list** — a horizontal row of `QPushButton` chips rebuilt dynamically in `ReviewPage._refresh_plate_list()` (review_page.py:1173-1210). Each chip is a child of the chips layout inside the Plate Detection group box (a descendant of ReviewPage). Clicking a chip fires `_on_plate_chip_clicked(idx)` (review_page.py:1212-1217), which selects the box in the overlay and rebuilds the chips. The chip that was clicked had `QPushButton`'s default `Qt.StrongFocus` focus policy, so the click transfers keyboard focus to the chip button. `_refresh_plate_list()` then calls `deleteLater()` on the old chips, destroying the widget that currently owns keyboard focus. No path in this flow calls anything equivalent to `_forward_focus()`.

This asymmetry is the root cause of the bug. After a chip-click-triggered delete:

- The focused chip is destroyed; Qt reassigns focus to an arbitrary ancestor/sibling that may or may not be inside the ReviewPage subtree.
- The next arrow-key press can still activate the `QShortcut` for `Key_Left`/`Key_Right` (its `WidgetWithChildrenShortcut` context may still match depending on where Qt parked the focus), which calls `start_step_hold(direction)`.
- The matching key *release* event does not reach `ReviewPage.keyReleaseEvent` because that handler is a direct override on `ReviewPage`, not a shortcut — it fires only when the focused widget is `ReviewPage` itself or forwards releases to it. With focus outside the ReviewPage subtree, the release is consumed elsewhere and `stop_step_hold()` never runs.
- The step-hold timer keeps advancing the player by one frame every 33 ms forever, which the user perceives as "the video started playing and I cannot stop it."

## Goals / Non-Goals

**Goals:**
- Eliminate the focus divergence between the canvas-click-delete path and the chip-click-delete path. After either interaction, keyboard focus and shortcut context MUST be identical to what they were before the interaction.
- Guarantee that `ReviewPage.keyReleaseEvent` always receives the matching release event for an arrow-key press handled by its `QShortcut`, so `stop_step_hold()` always runs.
- Fix the symptom (runaway playback after list-click-delete) by fixing the mechanism (focus escape on chip click), not by trapping the symptom.
- Add regression tests that would have caught this bug: click a chip, press Delete, press Right-arrow, release Right-arrow, assert the player is not in a hold-step state.

**Non-Goals:**
- Redesigning the plate chip list into a persistent widget (e.g., QListWidget). The dynamic-chip design is kept; only its focus behavior changes.
- Changing shortcut context from `Qt.WidgetWithChildrenShortcut`. It is the correct context for a page-scoped shortcut.
- Adding global (`Qt.ApplicationShortcut`) keyboard shortcuts. That would paper over focus bugs and risk conflicts with other pages.
- Touching canvas-click behavior. The canvas path already works and should remain the reference behavior.
- Changing video player transport behavior. No changes to `QMediaPlayer` wiring, `start_step_hold`, or `toggle_play`.

## Decisions

### Decision 1 — Make plate-chip buttons non-focusable (`Qt.NoFocus`)

Each dynamically created `QPushButton` chip in `_refresh_plate_list` will have `chip.setFocusPolicy(Qt.NoFocus)` set at creation time.

**Why:** `QPushButton` defaults to `Qt.StrongFocus`, which accepts focus both on Tab and on mouse click. A chip does not need keyboard focus — it has no `shortcut()`, it is not reachable by the user's navigation story (which uses arrow keys to step frames, not to traverse the chips), and the only action the chip supports is the `clicked` signal which fires regardless of focus state. Setting `Qt.NoFocus` means clicking a chip:
- Does not steal focus from whatever previously had it (typically `ReviewPage` itself).
- Does not leave focus on a widget that is about to be destroyed.
- Behaves exactly like the canvas path, where `PlateOverlayWidget` is already `Qt.NoFocus` and explicitly forwards focus back to the logical parent.

**Alternatives considered:**

- *Restore focus explicitly in `_on_plate_chip_clicked`* by calling `self.setFocus()` or replicating `PlateOverlayWidget._forward_focus()` on the ReviewPage. This would work, but it is a post-hoc correction that still allows a brief window in which the chip holds focus — that window is where the chip destruction happens in the delete path, so it is exactly where Qt's focus reassignment goes wrong. `Qt.NoFocus` prevents the problem at its origin.
- *Replace chips with a persistent `QListWidget`*. Solves focus stability because items are not destroyed/recreated, but is a much larger change that touches layout, styling, selection visuals, and all the signal wiring. Out of scope for a bug fix.
- *Install an event filter on the chip-row container that silently redirects focus back to ReviewPage*. More code, less obvious, and does not make the intent clear in the chip-creation code.

`Qt.NoFocus` is the smallest, most local change, and it aligns the chip behavior with the overlay's existing focus model.

### Decision 2 — Add a belt-and-suspenders focus restoration after chip interaction

In addition to Decision 1, `_on_plate_chip_clicked` will call a new `_restore_keyboard_focus()` helper on `ReviewPage`, mirroring `PlateOverlayWidget._forward_focus()`: it activates the top-level window if needed and calls `self.setFocus()` on the Review page.

**Why:** Even with `Qt.NoFocus` on chips, focus could already be on some other unrelated widget before the user's click (e.g., the user Tab-ed into something, or a prior interaction parked focus on the main window). Chip clicks are user-driven interactions that should leave the app in the same shortcut-ready state as canvas interactions. Centralizing this in one helper matches the overlay's pattern and makes it easy to call from any future chip-interaction code path without re-deriving the fix.

The helper is also called at the end of `_refresh_plate_list()` itself *only when the method was triggered by a user delete or click* — i.e., it is invoked from the chip-click handler and from the frame-delete handler, not from the debounced scroll-triggered refresh via `_schedule_plate_list_refresh`, to avoid stealing focus from other legitimate focus owners (e.g., the clip-info panel or the timeline) during passive UI updates.

**Alternatives considered:**

- *Always call `_restore_keyboard_focus()` at the end of `_refresh_plate_list()`*. Rejected: `_refresh_plate_list` is called on every frame change via `_schedule_plate_list_refresh`, and stealing focus on every timer tick could disrupt user interactions elsewhere (e.g., typing in a future search box, or clicking on the timeline ruler).
- *Only rely on Decision 1 (`Qt.NoFocus`) without a helper*. Likely sufficient for the reported bug, but leaves no defense if focus was already off the ReviewPage for unrelated reasons. The helper is a cheap defense; it also makes the Review page's invariant explicit — "after a chip interaction, ReviewPage owns keyboard focus" — so future maintainers have a single function to reason about.

### Decision 3 — Do not change `keyReleaseEvent` or `start_step_hold`/`stop_step_hold` semantics

**Why:** Once Decisions 1 and 2 guarantee that `ReviewPage` retains focus across chip interactions, the release event naturally reaches `keyReleaseEvent` and `stop_step_hold()` fires correctly. Adding a redundant "stop hold on focus-in" or "stop hold on timer watchdog" would mask future focus bugs instead of exposing them via tests. We keep the invariant strict: step-hold starts on arrow press, stops on arrow release, and both require ReviewPage focus — which is what the rest of the Review page already assumes.

### Decision 4 — Test the full user sequence, not just the focus state

Regression tests will simulate the user's exact sequence with `QTest`:
1. Load a ReviewPage with plate data on the current frame.
2. Simulate `QTest.mouseClick` on a plate chip button.
3. Simulate `QTest.keyClick(review_page, Qt.Key_Delete)`.
4. Simulate `QTest.keyPress(review_page, Qt.Key_Right)` then `QTest.keyRelease(review_page, Qt.Key_Right)`.
5. Assert: the expected plate was removed, the current frame advanced by exactly the step amount, and the player is not in a step-hold state (`_hold_step_direction == 0`, timers inactive).
6. Cross-check: the same sequence with a canvas click (instead of a chip click) produces the same end state. The regression is specifically the divergence between the two paths.

**Why:** A test that only asserts "ReviewPage has focus" would pass with a brittle fix. Asserting on player state (`_hold_step_direction`) captures the actual user-visible failure.

## Risks / Trade-offs

- **Risk:** Setting `Qt.NoFocus` on chips means Tab-navigation users cannot reach chips via keyboard. → **Mitigation:** The chips were never in the keyboard-navigation story to begin with — they have no keyboard activation path — so this is a non-regression. Users navigate with arrow keys (frame stepping) and Delete/Backspace (delete selection); chip selection is an explicit mouse affordance.

- **Risk:** `_restore_keyboard_focus()` steals focus at a moment the user did not expect. → **Mitigation:** It is called only from chip-interaction code paths (explicit user actions targeting the chips), not from passive refreshes. The canvas path already does the exact same thing with `_forward_focus()`, so users are already accustomed to this behavior on plate interactions.

- **Risk:** Activating the top-level window inside `_restore_keyboard_focus()` could grab window focus from another application if the user is multitasking. → **Mitigation:** Mirror the overlay's existing implementation (`plate_overlay.py:390-394`) — only call `activateWindow()` on the already-retrieved top-level — it is the same behavior shipped today for canvas clicks, so there is no new cross-app-focus risk.

- **Trade-off:** The fix deliberately does *not* add a watchdog to stop runaway `start_step_hold` if focus is lost mid-hold. If a future change introduces a different focus bug, the runaway symptom will recur. This is intentional: we want regressions to be loud and surfaced by the new tests, not silently papered over.

- **Trade-off:** Two small changes (focus policy + helper call) rather than a single one. The helper is defense-in-depth, not strictly required; it is justified because the cost is tiny and it documents the invariant explicitly.

## Migration Plan

None required. The change is a pure UI-behavior bug fix: no persisted data format changes, no config changes, no CLI changes. Rollback is simply reverting the change commit. No feature flag needed; the previous behavior is a bug.

## Open Questions

- None. Root cause is identified from code inspection, and the fix is fully local to `ReviewPage` chip wiring.
