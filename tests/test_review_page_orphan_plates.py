"""Orphan-plate warning: plates stored outside the current effective window.

If the user shortens `crossfade_duration` after placing plates in a clip's
tail, some plates fall outside the clip's effective window. The Review page
SHALL expose a signal/property the UI can bind to — we don't silently drop
those entries — and surface a visual affordance so the user can fix or
delete them.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.config import TransitionStyle
from trailvideocut.editor.models import CutPlan, EditDecision
from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.review_page import ReviewPage


FPS = 30.0

CLIP0 = EditDecision(
    beat_index=0, source_start=0.0, source_end=4.0,
    target_start=0.0, target_end=4.0, interest_score=1.0,
)
CLIP1 = EditDecision(
    beat_index=1, source_start=4.0, source_end=8.0,
    target_start=3.8, target_end=7.8, interest_score=0.9,
)


def _plan(crossfade: float) -> CutPlan:
    return CutPlan(
        decisions=[CLIP0, CLIP1],
        total_duration=8.0,
        song_tempo=120.0,
        transition_style=TransitionStyle.CROSSFADE.value,
        crossfade_duration=crossfade,
    )


def _make_page(qapp, plate_data=None, crossfade=0.2) -> ReviewPage:
    page = ReviewPage()
    plan = _plan(crossfade)
    page._timeline.set_data(plan.decisions, video_duration=8.0)
    page._cut_plan = plan
    page._video_path = "/fake.mp4"
    if plate_data is not None:
        page._plate_data = plate_data
    return page


class TestOrphanTailPlates:
    def test_no_orphans_when_all_plates_in_window(self, qapp):
        # 6-frame tail; a plate at frame 123 is inside the effective window.
        data = {
            0: ClipPlateData(
                clip_index=0,
                detections={123: [PlateBox(0.4, 0.5, 0.1, 0.05)]},
            ),
        }
        page = _make_page(qapp, plate_data=data, crossfade=0.2)
        try:
            orphans = page._orphan_tail_plates_by_clip()
            assert orphans.get(0, []) == []
        finally:
            page.close()

    def test_orphans_detected_after_shortening_crossfade(self, qapp):
        # Plate was stored at frame 124 with a 6-frame tail (effective end
        # exclusive = 126); shrinking crossfade to 0.05s cuts tail to
        # round(0.05*30)=2 frames → effective end exclusive = 122 → frame
        # 124 becomes an orphan.
        data = {
            0: ClipPlateData(
                clip_index=0,
                detections={124: [PlateBox(0.4, 0.5, 0.1, 0.05)]},
            ),
        }
        page = _make_page(qapp, plate_data=data, crossfade=0.05)
        try:
            orphans = page._orphan_tail_plates_by_clip()
            assert orphans.get(0) == [124]
        finally:
            page.close()

    def test_orphan_count_surfaces_in_clip_info_label(self, qapp):
        # Visual affordance: the clip-range read-out SHALL indicate the
        # orphan count and the tooltip SHALL carry the exact frame indices.
        data = {
            0: ClipPlateData(
                clip_index=0,
                detections={
                    80: [PlateBox(0.3, 0.5, 0.1, 0.05)],  # in-window core
                    200: [PlateBox(0.4, 0.5, 0.1, 0.05)],  # orphan
                },
            ),
        }
        page = _make_page(qapp, plate_data=data, crossfade=0.2)
        try:
            page._timeline.select_clip(0)
            page._show_clip_info(0)
            text = page._clip_info_label.text()
            tip = page._clip_info_label.toolTip()
            assert "1 out-of-window plate" in text
            assert "200" in tip
        finally:
            page.close()

    def test_plate_past_tail_end_is_orphan_even_with_default_crossfade(self, qapp):
        # A plate at absolute frame 200 (deep in clip 1's core range) stored
        # under clip 0 is an orphan regardless of tail length.
        data = {
            0: ClipPlateData(
                clip_index=0,
                detections={200: [PlateBox(0.4, 0.5, 0.1, 0.05)]},
            ),
        }
        page = _make_page(qapp, plate_data=data, crossfade=0.2)
        try:
            orphans = page._orphan_tail_plates_by_clip()
            assert orphans.get(0) == [200]
        finally:
            page.close()
