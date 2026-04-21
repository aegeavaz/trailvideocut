"""Unit tests for `tail_frames` / `clip_frame_window` helpers.

These helpers define the "effective" source-frame window of a clip for plate
management: the core range `[source_start_frame, source_end_frame)` plus an
optional transition tail for non-last crossfade clips.
"""
from __future__ import annotations

import pytest

from trailvideocut.config import TransitionStyle
from trailvideocut.editor.models import (
    CutPlan,
    EditDecision,
    clip_frame_window,
    tail_frames,
)


def _decision(
    source_start: float,
    source_end: float,
    target_start: float = 0.0,
    target_end: float = 0.0,
    score: float = 0.5,
) -> EditDecision:
    return EditDecision(
        beat_index=0,
        source_start=source_start,
        source_end=source_end,
        target_start=target_start,
        target_end=target_end,
        interest_score=score,
    )


def _plan(
    decisions: list[EditDecision],
    transition_style: str = TransitionStyle.CROSSFADE.value,
    crossfade_duration: float = 0.2,
) -> CutPlan:
    return CutPlan(
        decisions=decisions,
        total_duration=decisions[-1].target_end if decisions else 0.0,
        song_tempo=120.0,
        transition_style=transition_style,
        crossfade_duration=crossfade_duration,
    )


class TestTailFrames:
    def test_non_last_crossfade_clip_has_tail(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0), _decision(8.0, 12.0)],
            crossfade_duration=0.2,
        )
        assert tail_frames(0, plan, fps=30.0) == 6
        assert tail_frames(1, plan, fps=30.0) == 6

    def test_last_clip_has_no_tail(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0), _decision(8.0, 12.0)],
            crossfade_duration=0.2,
        )
        assert tail_frames(2, plan, fps=30.0) == 0

    def test_cut_plan_has_no_tail(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0)],
            transition_style=TransitionStyle.HARD_CUT.value,
            crossfade_duration=0.2,
        )
        assert tail_frames(0, plan, fps=30.0) == 0
        assert tail_frames(1, plan, fps=30.0) == 0

    def test_zero_crossfade_duration_has_no_tail(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0)],
            crossfade_duration=0.0,
        )
        assert tail_frames(0, plan, fps=30.0) == 0

    def test_non_integer_fps_rounds(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0)],
            crossfade_duration=0.2,
        )
        # 0.2 * 29.97 = 5.994 → round → 6
        assert tail_frames(0, plan, fps=29.97) == 6
        # 0.2 * 23.976 = 4.7952 → round → 5
        assert tail_frames(0, plan, fps=23.976) == 5

    def test_single_clip_plan_has_no_tail(self):
        plan = _plan([_decision(0.0, 4.0)], crossfade_duration=0.2)
        assert tail_frames(0, plan, fps=30.0) == 0

    def test_out_of_range_clip_index_returns_zero(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0)],
            crossfade_duration=0.2,
        )
        assert tail_frames(5, plan, fps=30.0) == 0
        with pytest.raises(IndexError):
            # negative doesn't make sense — the helper only guards the upper
            # edge because that's the only "last clip" check; negative is a
            # programmer error that should surface loudly.
            tail_frames(-5, plan, fps=30.0)


class TestClipFrameWindow:
    def test_non_last_crossfade_window_extended_by_tail(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0), _decision(8.0, 12.0)],
            crossfade_duration=0.2,
        )
        start, end = clip_frame_window(0, plan, fps=30.0)
        # Core: [0, 120). Tail: 6. Effective: [0, 126).
        assert start == 0
        assert end == 126

    def test_last_clip_window_unchanged(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0)],
            crossfade_duration=0.2,
        )
        start, end = clip_frame_window(1, plan, fps=30.0)
        # Last clip: [120, 240) (no tail).
        assert start == 120
        assert end == 240

    def test_cut_plan_window_matches_core_range(self):
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0)],
            transition_style=TransitionStyle.HARD_CUT.value,
            crossfade_duration=0.2,
        )
        start, end = clip_frame_window(0, plan, fps=30.0)
        assert start == 0
        assert end == 120

    def test_non_integer_fps_uses_round_semantics(self):
        # Use OTIO's round(t*fps) convention so UI, exporter, and storage agree.
        plan = _plan(
            [_decision(0.0, 4.0), _decision(4.0, 8.0)],
            crossfade_duration=0.2,
        )
        start, end = clip_frame_window(0, plan, fps=29.97)
        # round(0.0*29.97)=0, round(4.0*29.97)=120, tail=round(0.2*29.97)=6 → end=126
        assert start == 0
        assert end == 126
