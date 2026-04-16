## ADDED Requirements

### Requirement: Plate chips SHALL NOT accept keyboard focus
Each plate chip button displayed in the Plate Detection panel SHALL have a non-focusable focus policy, so that clicking a chip never transfers keyboard focus away from the Review page. This mirrors the overlay's existing behavior (the overlay widget is non-focusable and explicitly forwards focus to the Review page).

#### Scenario: Clicking a chip keeps focus on the Review page
- **WHEN** the Review page currently has keyboard focus and the user clicks a plate chip with the left mouse button
- **THEN** keyboard focus SHALL remain on the Review page (or on a widget whose keyboard events are dispatched to the Review page), and no chip button SHALL report `hasFocus() == True` after the click

#### Scenario: Clicking a chip before a chip rebuild
- **WHEN** the user clicks a plate chip and the click handler triggers `_refresh_plate_list()` (which destroys and recreates chips)
- **THEN** the destroyed chip SHALL NOT have been the focus owner, so Qt SHALL NOT need to reassign keyboard focus as a side effect of widget destruction

### Requirement: Plate-list interactions SHALL preserve Review-page shortcut context
After any user interaction with the plate chip list (click, selection, delete via chip), the Review page SHALL own keyboard focus and its page-scoped keyboard shortcuts (frame stepping, play toggle, delete, escape, jump) SHALL remain active and equivalent to their state before the interaction.

#### Scenario: Arrow-key frame navigation after chip click
- **WHEN** the user clicks a plate chip on the current frame and then presses the Right arrow key
- **THEN** the Review page's step-forward shortcut SHALL fire exactly once (no auto-repeat while the key is held is part of the shortcut, but the `start_step_hold` hold-timer is managed separately and is bounded by key release), advancing the player by one frame

#### Scenario: Arrow-key release after chip click
- **WHEN** the user clicks a plate chip, presses the Right arrow key, and then releases the Right arrow key
- **THEN** the Review page's `keyReleaseEvent` SHALL receive the release and `stop_step_hold()` SHALL run, leaving the player's `_hold_step_direction` at 0 and its hold-step timers inactive

### Requirement: Deleting via the chip list SHALL behave identically to deleting via the canvas
The end state of the application after deleting a plate via a chip click followed by the Delete key SHALL be indistinguishable from the end state after deleting the same plate via a canvas click followed by the Delete key, with respect to: keyboard focus owner, active shortcut context, player playback state, player hold-step state, selected plate index on the overlay, and the list of remaining boxes in the chip list.

#### Scenario: Equivalence of the two delete paths
- **WHEN** the application is in the same starting state (same frame, same plate data, same selection) and the user performs either path A (click plate on canvas → press Delete) or path B (click plate chip → press Delete)
- **THEN** the post-interaction state along all of the following axes SHALL be identical: focus owner is the Review page, no chip widget has focus, player is paused, `_hold_step_direction == 0`, the expected plate is removed from the current frame's detection data, and the chip list reflects the remaining boxes

#### Scenario: Runaway playback regression guard
- **WHEN** the user clicks a plate chip, presses Delete, then presses and releases the Right arrow key once
- **THEN** the player SHALL advance by exactly one frame, it SHALL NOT enter an unbounded auto-step state, and no `hold_step_delay_timer` or `hold_step_timer` on the video player SHALL remain active after the key release
