"""Regression tests for the plate-list keyboard-focus bug.

After clicking a plate chip in the Plate Detection panel and deleting it, the
Review page must keep keyboard focus and its page-scoped shortcuts must keep
working. Previously, clicking a chip transferred focus to the chip button,
then destroying the chip left focus outside the Review page, causing the next
arrow-key press to start an unbounded hold-step (seen by the user as runaway
playback).

Tests run under the Qt `offscreen` platform, where window activation and
mouse-driven focus transitions are not fully modeled. We therefore test the
fix invariants directly (focus policy, the focus-restoring helper, handler
behavior) rather than relying on end-to-end QShortcut dispatch.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.review_page import ReviewPage


CURRENT_FRAME = 42


def _make_two_box_clip() -> ClipPlateData:
    return ClipPlateData(
        clip_index=0,
        detections={
            CURRENT_FRAME: [
                PlateBox(x=0.10, y=0.20, w=0.15, h=0.08, confidence=0.9, manual=False),
                PlateBox(x=0.55, y=0.60, w=0.15, h=0.08, confidence=0.8, manual=False),
            ],
        },
    )


def _prime_page(page: ReviewPage, clip_data: ClipPlateData) -> None:
    """Seed a ReviewPage with plate data so `_refresh_plate_list()` has chips to render.

    Mirrors what the normal app flow does when entering a clip with detections:
    register clip data, point the overlay at it, position the overlay on the
    current frame, and build the chip row.
    """
    page._plate_data[0] = clip_data
    page._plate_overlay.set_clip_data(clip_data)
    page._plate_overlay.set_current_frame(CURRENT_FRAME, force=True)
    page._refresh_plate_list()


def _chip_buttons(page: ReviewPage) -> list[QPushButton]:
    buttons: list[QPushButton] = []
    for i in range(page._plate_chips_layout.count()):
        widget = page._plate_chips_layout.itemAt(i).widget()
        if isinstance(widget, QPushButton):
            buttons.append(widget)
    return buttons


def _hold_step_timers_inactive(page: ReviewPage) -> bool:
    player = page._player
    delay = player._hold_step_delay_timer
    step = player._hold_step_timer
    delay_inactive = delay is None or not delay.isActive()
    step_inactive = step is None or not step.isActive()
    return delay_inactive and step_inactive


@pytest.fixture
def review_page(qapp):
    page = ReviewPage()
    page.show()
    QTest.qWait(10)  # let the event loop settle so layout/focus are wired up
    yield page
    page.close()
    page.deleteLater()
    QTest.qWait(10)


# ---------------------------------------------------------------------------
# Test 1 — declarative: chip buttons must not accept keyboard focus.
# ---------------------------------------------------------------------------

def test_plate_chips_are_not_focusable(review_page):
    _prime_page(review_page, _make_two_box_clip())
    chips = _chip_buttons(review_page)

    assert len(chips) == 2, "primer should produce one chip per box"
    for chip in chips:
        assert chip.focusPolicy() == Qt.NoFocus, (
            "plate chips must not accept keyboard focus — otherwise clicking a chip "
            "would steal focus from the Review page and break arrow-key navigation"
        )


# ---------------------------------------------------------------------------
# Test 2 — the chip-click handler restores focus to the Review page.
#
# Simulates the buggy pre-click state (focus elsewhere) and asserts that
# processing a chip click leaves ReviewPage as the focus widget.
# ---------------------------------------------------------------------------

def test_on_plate_chip_clicked_restores_focus_to_page(review_page):
    _prime_page(review_page, _make_two_box_clip())

    # Simulate the condition that the buggy code produced: some other widget
    # owning focus at the moment the chip-click handler runs.
    decoy = QPushButton("decoy", review_page)
    decoy.setFocusPolicy(Qt.StrongFocus)
    decoy.show()
    decoy.setFocus()
    QTest.qWait(5)
    assert decoy.hasFocus(), "test precondition: decoy owns focus"

    review_page._on_plate_chip_clicked(0)

    assert review_page.hasFocus(), (
        "after a chip click, keyboard focus must be restored to the Review page "
        "so page-scoped shortcuts (arrows, Space, Delete) dispatch correctly"
    )
    for chip in _chip_buttons(review_page):
        assert not chip.hasFocus(), (
            "no chip may retain focus after the click handler runs"
        )


# ---------------------------------------------------------------------------
# Test 3 — passive list refreshes (scrub-driven) must NOT steal focus.
#
# `_refresh_plate_list()` is also invoked on every frame change via
# `_schedule_plate_list_refresh`. Stealing focus on every tick would disrupt
# unrelated interactions. The fix restores focus only from the click handler.
# ---------------------------------------------------------------------------

def test_refresh_plate_list_does_not_steal_focus(review_page):
    _prime_page(review_page, _make_two_box_clip())

    decoy = QPushButton("decoy", review_page)
    decoy.setFocusPolicy(Qt.StrongFocus)
    decoy.show()
    decoy.setFocus()
    QTest.qWait(5)
    assert decoy.hasFocus(), "test precondition: decoy owns focus"

    # Passive refresh (as fired by the debounced scrub timer).
    review_page._refresh_plate_list()

    assert decoy.hasFocus(), (
        "_refresh_plate_list must not steal focus on passive refreshes — focus "
        "restoration belongs in the explicit chip-click handler only"
    )


# ---------------------------------------------------------------------------
# Test 4 — end-to-end handler sequence: chip click → delete → arrow press →
# arrow release. Uses direct handler invocation instead of QShortcut dispatch
# (which is unreliable under offscreen Qt), but still exercises the real
# keyReleaseEvent override and stop_step_hold path.
# ---------------------------------------------------------------------------

def test_delete_via_chip_then_arrow_does_not_leave_hold_step_active(review_page):
    _prime_page(review_page, _make_two_box_clip())
    review_page.setFocus()

    # --- Chip click path: select first plate via its chip. ---
    chips = _chip_buttons(review_page)
    assert len(chips) == 2
    review_page._on_plate_chip_clicked(0)
    assert review_page._plate_overlay._selected_idx == 0
    assert review_page.hasFocus(), "page must retain focus after chip click"

    # --- Delete the selected plate (Delete key). ---
    review_page._on_delete_key()
    remaining = review_page._plate_data[0].detections.get(CURRENT_FRAME, [])
    assert len(remaining) == 1, "delete should remove exactly the selected plate"
    assert remaining[0].x == pytest.approx(0.55)

    # --- Press Right arrow: starts hold-step timer. ---
    review_page._on_step_forward_pressed()
    assert review_page._player._hold_step_direction == 1, (
        "pressing Right should start hold-step in direction +1"
    )

    # --- Release Right arrow: the override must reset hold-step. ---
    release_event = QKeyEvent(
        QKeyEvent.KeyRelease, Qt.Key_Right, Qt.NoModifier, "", False
    )
    review_page.keyReleaseEvent(release_event)

    assert review_page._player._hold_step_direction == 0, (
        "hold-step direction must reset to 0 after key release; otherwise the "
        "player keeps stepping forever (user-visible as runaway playback)"
    )
    assert _hold_step_timers_inactive(review_page), (
        "hold-step delay/tick timers must be inactive after key release"
    )


# ---------------------------------------------------------------------------
# Test 5 — regression guard for the canvas path: the existing overlay
# `_forward_focus` still lands focus on the Review page.
#
# This codifies the reference behavior we're aligning the chip path with,
# so future refactors of `_forward_focus` don't silently regress it.
# ---------------------------------------------------------------------------

def test_canvas_forward_focus_lands_inside_review_page_subtree(review_page):
    _prime_page(review_page, _make_two_box_clip())

    decoy = QPushButton("decoy", review_page)
    decoy.setFocusPolicy(Qt.StrongFocus)
    decoy.show()
    decoy.setFocus()
    QTest.qWait(5)
    assert decoy.hasFocus(), "test precondition: decoy owns focus"

    review_page._plate_overlay._forward_focus()

    focus_widget = QApplication.focusWidget()
    # `_forward_focus` targets `_logical_parent` (the VideoPlayer, not the page
    # itself) — what matters for Qt.WidgetWithChildrenShortcut is that the
    # focus widget lives somewhere under ReviewPage.
    assert focus_widget is not None, "something must own focus after _forward_focus"
    assert (
        focus_widget is review_page or review_page.isAncestorOf(focus_widget)
    ), (
        "focus must land inside the ReviewPage subtree so page-scoped shortcuts "
        f"dispatch correctly; got focus on {focus_widget!r}"
    )
