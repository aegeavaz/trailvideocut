"""ReviewPage._on_add_plate SHALL inherit rotation from the reference
detection used (projection or nearest clone); fallback (no refs) SHALL
stay axis-aligned.

fix-plate-box-handlers / group 6.
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
    # Pin the current frame so projection/target frame are deterministic.
    page._player.frame_at = lambda *_: 60
    page._plate_overlay.set_current_frame(60)
    # The overlay must be visible for _on_add_plate to proceed.
    page._plate_overlay.setVisible(True)
    return page


class TestAddPlateInheritsAngle:
    def test_nearest_reference_clone_inherits_angle(self, qapp):
        """Single-reference clone: new box copies position, size AND angle."""
        page = _make_page(qapp)
        try:
            page._plate_data[0] = ClipPlateData(
                clip_index=0,
                detections={
                    40: [PlateBox(x=0.4, y=0.45, w=0.2, h=0.05, angle=12.0)],
                },
            )
            page._plate_overlay.set_clip_data(page._plate_data[0])

            page._on_add_plate()

            new_boxes = page._plate_data[0].detections.get(60, [])
            assert len(new_boxes) == 1
            added = new_boxes[0]
            assert added.manual is True
            assert added.angle == pytest.approx(12.0)
        finally:
            page.close()

    def test_motion_projection_inherits_nearest_angle(self, qapp):
        """Projection: angle inherited from the nearest reference used."""
        page = _make_page(qapp)
        try:
            page._plate_data[0] = ClipPlateData(
                clip_index=0,
                detections={
                    40: [PlateBox(x=0.40, y=0.50, w=0.10, h=0.05, angle=15.0)],
                    50: [PlateBox(x=0.45, y=0.50, w=0.10, h=0.05, angle=15.0)],
                },
            )
            page._plate_overlay.set_clip_data(page._plate_data[0])

            page._on_add_plate()

            new_boxes = page._plate_data[0].detections.get(60, [])
            assert len(new_boxes) == 1
            added = new_boxes[0]
            assert added.manual is True
            assert added.angle == pytest.approx(15.0)
        finally:
            page.close()

    def test_no_reference_fallback_is_axis_aligned(self, qapp):
        """No references anywhere — fallback must stay angle==0."""
        page = _make_page(qapp)
        try:
            page._plate_data[0] = ClipPlateData(clip_index=0)
            page._plate_overlay.set_clip_data(page._plate_data[0])

            page._on_add_plate(cursor_nx=0.5, cursor_ny=0.5)

            new_boxes = page._plate_data[0].detections.get(60, [])
            assert len(new_boxes) == 1
            added = new_boxes[0]
            assert added.manual is True
            assert added.angle == pytest.approx(0.0)
        finally:
            page.close()
