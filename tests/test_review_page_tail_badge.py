"""Review-page clip-range read-out shows the transition-tail frame count.

Covers the plate-clip-transition-tail requirement: when the selected clip
has a non-zero tail, the read-out SHALL append `+ N tail frames`, and when
the playhead is inside the tail the read-out (or a co-located tooltip)
SHALL indicate the position within the tail (e.g. `tail 3/6`).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.config import TransitionStyle
from trailvideocut.editor.models import CutPlan, EditDecision
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


def _plan(crossfade: float = 0.2) -> CutPlan:
    return CutPlan(
        decisions=[CLIP0, CLIP1],
        total_duration=8.0,
        song_tempo=120.0,
        transition_style=TransitionStyle.CROSSFADE.value,
        crossfade_duration=crossfade,
    )


def _make_page(qapp) -> ReviewPage:
    page = ReviewPage()
    plan = _plan()
    page._timeline.set_data(plan.decisions, video_duration=8.0)
    page._cut_plan = plan
    page._video_path = "/fake.mp4"
    return page


def _seek_to_frame(page: ReviewPage, frame: int) -> None:
    seconds = frame / FPS
    page._player.frame_at = lambda *_: frame
    page._player._player.position = lambda: int(seconds * 1000)


class TestClipRangeBadge:
    def test_tail_frame_suffix_for_non_last_crossfade_clip(self, qapp):
        page = _make_page(qapp)
        try:
            page._timeline.select_clip(0)
            page._show_clip_info(0)
            text = page._clip_info_label.text()
            # 0.2s × 30 fps = 6 tail frames.
            assert "+ 6 tail frames" in text
        finally:
            page.close()

    def test_no_tail_suffix_for_last_clip(self, qapp):
        page = _make_page(qapp)
        try:
            page._timeline.select_clip(1)
            page._show_clip_info(1)
            text = page._clip_info_label.text()
            assert "tail frames" not in text
        finally:
            page.close()

    def test_in_tail_indicator_when_playhead_in_tail(self, qapp):
        page = _make_page(qapp)
        try:
            page._timeline.select_clip(0)
            # Seek to tail position 3 of 6 (frames 120..125 → frame 122 = pos 3/6).
            _seek_to_frame(page, 122)
            page._show_clip_info(0)
            text = page._clip_info_label.text()
            # Either the label or its tooltip SHALL carry `tail 3/6`.
            combined = text + " " + (page._clip_info_label.toolTip() or "")
            assert "tail 3/6" in combined
        finally:
            page.close()
