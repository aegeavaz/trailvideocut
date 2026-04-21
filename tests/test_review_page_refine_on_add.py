"""Regression: Refine buttons SHALL activate immediately after adding
the first plate to a clip/frame.

fix-plate-box-handlers / group 5.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.editor.models import EditDecision
from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.review_page import ReviewPage


def _make_page(qapp) -> ReviewPage:
    page = ReviewPage()
    clip = EditDecision(
        beat_index=0,
        source_start=0.0, source_end=5.0,
        target_start=0.0, target_end=5.0,
        interest_score=1.0,
    )
    page._timeline.set_data([clip], video_duration=5.0)
    page._timeline.select_clip(0)
    page._video_path = "/fake.mp4"
    # Pretend we're at frame 0 so add_box writes there.
    page._player.frame_at = lambda *_: 0
    page._plate_overlay.set_current_frame(0)
    return page


class TestRefineButtonsActivateAfterFirstAdd:
    def test_first_add_enables_both_refine_buttons(self, qapp):
        """A clip with zero detections should, after an overlay-driven
        add_box, have both Refine Clip and Refine Frame enabled without
        any frame navigation."""
        page = _make_page(qapp)
        try:
            page._plate_data[0] = ClipPlateData(clip_index=0)
            page._plate_overlay.set_clip_data(page._plate_data[0])
            page._update_frame_buttons()
            assert page._btn_refine_clip_plates.isEnabled() is False
            assert page._btn_refine_frame_plates.isEnabled() is False

            # Add a plate on the current frame.
            page._plate_overlay.add_box(
                PlateBox(x=0.4, y=0.45, w=0.1, h=0.05, manual=True),
            )

            assert page._btn_refine_clip_plates.isEnabled() is True
            assert page._btn_refine_frame_plates.isEnabled() is True
            assert page._btn_clear_clip_plates.isEnabled() is True
            assert page._btn_clear_frame_plates.isEnabled() is True
        finally:
            page.close()

    def test_deleting_last_plate_on_frame_disables_frame_buttons(self, qapp):
        """Deleting the last plate on a frame should disable the frame-
        level buttons immediately."""
        page = _make_page(qapp)
        try:
            page._plate_data[0] = ClipPlateData(
                clip_index=0,
                detections={
                    0: [PlateBox(x=0.4, y=0.45, w=0.1, h=0.05, manual=True)],
                    5: [PlateBox(x=0.4, y=0.45, w=0.1, h=0.05, manual=True)],
                },
            )
            page._plate_overlay.set_clip_data(page._plate_data[0])
            page._plate_overlay.select_box(0)
            page._update_frame_buttons()
            assert page._btn_refine_frame_plates.isEnabled() is True

            page._plate_overlay.delete_selected()

            assert page._btn_refine_frame_plates.isEnabled() is False
            # Clip-level still has frame 5, so clip buttons stay enabled.
            assert page._btn_refine_clip_plates.isEnabled() is True
        finally:
            page.close()
