"""Regression tests for the plate-overlay "Clear Clip Plates" confirmation flicker.

The plate overlay (`PlateOverlayWidget`) is a top-level transparent window,
so the WM can hide it when a modal `QMessageBox` appears. Before the fix, if
the user clicked "Clear Clip Plates" and the WM hid the overlay during the
modal, the overlay was not restored on "No" — the user had to leave and
re-enter the Review page to see the plates again. The fix restores the
overlay deterministically at the call-site after the modal returns.

Tests run under Qt's `offscreen` platform. Because we cannot drive the real
modal loop, we monkey-patch `QMessageBox.question` to (a) inject a WM-style
hide of the overlay mid-modal and (b) return the desired user choice. This
lets us assert the post-modal overlay state that the fix must guarantee.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from trailvideocut.editor.models import EditDecision
from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.review_page import ReviewPage


CURRENT_FRAME = 42


def _box(x=0.10, y=0.20, w=0.15, h=0.08, confidence=0.9, manual=False) -> PlateBox:
    return PlateBox(x=x, y=y, w=w, h=h, confidence=confidence, manual=manual)


def _clip_with_boxes(boxes: list[PlateBox] | None = None) -> ClipPlateData:
    if boxes is None:
        boxes = [_box()]
    return ClipPlateData(
        clip_index=0,
        detections={CURRENT_FRAME: list(boxes)},
    )


def _prime_review_page(
    page: ReviewPage,
    plate_data: dict[int, ClipPlateData],
    *,
    selected: int,
) -> None:
    """Seed ReviewPage with enough timeline clips and plate data to exercise
    `_on_clear_clip_plates`.

    Mirrors what `_on_plate_detection_finished` does in the real app: fill
    `_plate_data`, enable the Show Plates checkbox, point the overlay at the
    selected clip, and make the overlay visible.
    """
    max_idx = max(plate_data.keys()) if plate_data else 0
    clips = [
        EditDecision(
            beat_index=i,
            source_start=float(i) * 5.0,
            source_end=float(i + 1) * 5.0,
            target_start=0.0,
            target_end=5.0,
            interest_score=0.0,
        )
        for i in range(max_idx + 1)
    ]
    page._timeline._clips = clips
    page._timeline._selected = selected

    page._plate_data = dict(plate_data)
    page._chk_show_plates.setEnabled(True)
    page._chk_show_plates.setChecked(True)
    page._btn_add_plate.setEnabled(True)
    page._btn_clear_plates.setEnabled(True)
    page._btn_clear_clip_plates.setEnabled(True)
    page._btn_clear_frame_plates.setEnabled(
        selected in plate_data
        and CURRENT_FRAME in plate_data[selected].detections
    )

    page._plate_overlay.set_clip_data(plate_data[selected])
    page._plate_overlay.set_current_frame(CURRENT_FRAME, force=True)
    page._plate_overlay.setVisible(True)


@pytest.fixture
def review_page(qapp):
    page = ReviewPage()
    page.show()
    QTest.qWait(10)
    yield page
    page.close()
    page.deleteLater()
    QTest.qWait(10)


# ---------------------------------------------------------------------------
# 1.2 — Cancel path must restore the overlay even if WM hid it mid-modal.
# ---------------------------------------------------------------------------

def test_clear_clip_plates_cancel_keeps_overlay_visible(review_page, monkeypatch):
    clip_data = _clip_with_boxes()
    _prime_review_page(review_page, {0: clip_data}, selected=0)

    overlay = review_page._plate_overlay
    pre_clip_data = review_page._plate_data[0]
    assert overlay.isVisible(), "primer must leave overlay visible"

    def fake_question(*_args, **_kwargs):
        # Simulate the WM hiding this top-level overlay while the modal runs.
        overlay.setVisible(False)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", fake_question)

    review_page._on_clear_clip_plates()

    # --- Data must be untouched (No path preserves everything). ---
    assert 0 in review_page._plate_data
    assert review_page._plate_data[0] is pre_clip_data, (
        "cancel must not replace the ClipPlateData object"
    )
    assert CURRENT_FRAME in pre_clip_data.detections
    assert len(pre_clip_data.detections[CURRENT_FRAME]) == 1

    # --- Overlay must be restored despite the WM-hide mid-modal. ---
    assert overlay.isVisible() is True, (
        "after cancel, the overlay MUST be re-shown even if the WM hid it "
        "during the confirmation dialog"
    )
    assert overlay._clip_data is pre_clip_data, (
        "overlay must still be pointed at the same clip data after cancel"
    )
    # After restoration, the overlay SHALL reflect the player's current frame
    # (not some arbitrary pre-call value). In the real app the player hasn't
    # moved during the modal, so this matches what the user saw before. In the
    # test harness the player has no media loaded, so current_time is 0.
    expected_frame = review_page._player.frame_at(review_page._player.current_time)
    assert overlay._current_frame == expected_frame, (
        "overlay must be synced to the player's current frame after restoration"
    )


# ---------------------------------------------------------------------------
# 1.3 — Confirm path on the only clip: data cleared, overlay hidden.
# ---------------------------------------------------------------------------

def test_clear_clip_plates_confirm_clears_data_and_rehomes_overlay(
    review_page, monkeypatch
):
    _prime_review_page(review_page, {0: _clip_with_boxes()}, selected=0)

    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_kw: QMessageBox.Yes
    )

    review_page._on_clear_clip_plates()

    assert review_page._plate_data == {}, "Yes on only-clip must clear plate data"
    assert review_page._plate_overlay._clip_data is None
    assert review_page._plate_overlay.isVisible() is False
    assert not review_page._btn_clear_clip_plates.isEnabled()
    assert not review_page._btn_clear_frame_plates.isEnabled()
    assert not review_page._btn_add_plate.isEnabled()
    assert not review_page._btn_clear_plates.isEnabled()


# ---------------------------------------------------------------------------
# 1.4 — Confirm path with another clip remaining: remaining data untouched,
# overlay synced and visible per show-plates checkbox (even if WM hid it).
# ---------------------------------------------------------------------------

def test_clear_clip_plates_confirm_with_other_clips_keeps_overlay_synced(
    review_page, monkeypatch
):
    clip_a = _clip_with_boxes([_box(x=0.10)])
    clip_b = _clip_with_boxes([_box(x=0.70)])
    _prime_review_page(review_page, {0: clip_a, 1: clip_b}, selected=0)

    def fake_question(*_args, **_kwargs):
        review_page._plate_overlay.setVisible(False)  # simulate WM-hide
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)

    review_page._on_clear_clip_plates()

    # --- Other clip's data preserved. ---
    assert 0 not in review_page._plate_data
    assert 1 in review_page._plate_data
    assert review_page._plate_data[1] is clip_b, (
        "clearing one clip must not replace the other clip's data object"
    )
    assert CURRENT_FRAME in clip_b.detections
    assert clip_b.detections[CURRENT_FRAME][0].x == pytest.approx(0.70)

    # --- Overlay synced to the (still-selected) cleared clip: no data. ---
    assert review_page._plate_overlay._clip_data is None, (
        "overlay must reflect that the selected clip no longer has data"
    )

    # --- Overlay still visible (show-plates checked) even though WM hid it. ---
    assert review_page._plate_overlay.isVisible() is True, (
        "after Yes on a clip with other clips remaining, the overlay must be "
        "re-shown so the user sees the (empty) overlay for the still-selected "
        "clip, not a phantom-hidden overlay"
    )
