"""Tests for the transition-tail band on the Review timeline.

Covers the plate-clip-transition-tail spec requirement that every non-last
crossfade clip SHALL render a visually distinct tail sub-band whose width
matches `tail_frames(...)` at the current timeline scale.

The timeline is a custom-painted QWidget, so we don't compare pixels.
Instead we inspect the structural helper `_tail_band_rect(clip_index)`
that the render path uses as its single source of truth.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.config import TransitionStyle
from trailvideocut.editor.models import CutPlan, EditDecision
from trailvideocut.ui.timeline import TimelineWidget


def _plan(
    decisions: list[EditDecision],
    transition_style: str = TransitionStyle.CROSSFADE.value,
    crossfade_duration: float = 0.2,
) -> CutPlan:
    return CutPlan(
        decisions=decisions,
        total_duration=decisions[-1].source_end,
        song_tempo=120.0,
        transition_style=transition_style,
        crossfade_duration=crossfade_duration,
    )


def _dec(start: float, end: float) -> EditDecision:
    return EditDecision(
        beat_index=0,
        source_start=start, source_end=end,
        target_start=start, target_end=end,
        interest_score=0.5,
    )


@pytest.fixture
def timeline(qapp) -> TimelineWidget:
    t = TimelineWidget()
    t.resize(800, 80)
    t.show()
    yield t
    t.close()


class TestTailBandRectRendering:
    def test_non_last_crossfade_clip_has_tail_band(self, timeline):
        # 3-clip crossfade plan; fps=30, crossfade=0.2s ⇒ 6 tail frames.
        plan = _plan([_dec(0.0, 4.0), _dec(4.0, 8.0), _dec(8.0, 12.0)])
        timeline.set_data(plan.decisions, video_duration=12.0)
        timeline.set_transition_info(plan, fps=30.0)

        rect0 = timeline._tail_band_rect(0)
        rect1 = timeline._tail_band_rect(1)
        rect2 = timeline._tail_band_rect(2)
        assert rect0 is not None
        assert rect1 is not None
        assert rect2 is None  # last clip has no tail

        # The tail band's width at the timeline's pixel-per-second scale
        # SHALL equal ≈ 6 frames / 30 fps = 0.2s worth of pixels.
        track_width = timeline._track_width()
        expected_px = 0.2 / 12.0 * track_width
        assert rect0.width() == pytest.approx(expected_px, abs=1.0)

    def test_cut_plan_has_no_tail_band(self, timeline):
        plan = _plan(
            [_dec(0.0, 4.0), _dec(4.0, 8.0)],
            transition_style=TransitionStyle.HARD_CUT.value,
        )
        timeline.set_data(plan.decisions, video_duration=8.0)
        timeline.set_transition_info(plan, fps=30.0)

        assert timeline._tail_band_rect(0) is None
        assert timeline._tail_band_rect(1) is None

    def test_missing_transition_info_falls_back_to_no_band(self, timeline):
        # If set_transition_info was never called, the timeline should
        # render without tail bands (defensive default) instead of raising.
        plan = _plan([_dec(0.0, 4.0), _dec(4.0, 8.0)])
        timeline.set_data(plan.decisions, video_duration=8.0)
        # Deliberately NOT calling set_transition_info.

        assert timeline._tail_band_rect(0) is None
        assert timeline._tail_band_rect(1) is None
