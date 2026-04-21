"""Assembler SHALL widen non-last crossfade segments to cover the tail.

Regression guard for the plate-clip-transition-tail capability: the blur
path ships plate data through ``PlateBlurProcessor.process_segment`` whose
iteration stops at ``segment_start + segment_duration``. If the assembler's
``_build_segments`` doesn't extend the non-last crossfade segment by
``crossfade_duration``, tail-region plates are never reached regardless of
where they are stored.
"""
from __future__ import annotations

from types import SimpleNamespace

from trailvideocut.config import TransitionStyle
from trailvideocut.editor.assembler import VideoAssembler
from trailvideocut.editor.models import CutPlan, EditDecision


def _plan(crossfade: float) -> CutPlan:
    return CutPlan(
        decisions=[
            EditDecision(0, 0.0, 4.0, 0.0, 4.0, 1.0),
            EditDecision(1, 4.0, 8.0, 3.8, 7.8, 1.0),
        ],
        total_duration=8.0,
        song_tempo=120.0,
        transition_style=TransitionStyle.CROSSFADE.value,
        crossfade_duration=crossfade,
    )


class _AsmStub:
    """Minimal Assembler-like object exposing `_build_segments` only."""

    def __init__(self, crossfade: float = 0.2, fps: float = 30.0):
        self.config = SimpleNamespace(
            output_fps=fps,
            crossfade_duration=crossfade,
            transition_style=TransitionStyle.CROSSFADE,
        )


def _call_build_segments(crossfade: float, fps: float = 30.0):
    """Invoke VideoAssembler._build_segments as an unbound method on a stub.

    Avoids constructing a full Assembler (which requires a real video path
    and a lot of surrounding state) while still exercising the real
    segment-building logic.
    """
    stub = _AsmStub(crossfade=crossfade, fps=fps)
    plan = _plan(crossfade)
    # Plenty of source duration so clamp-to-available-source does nothing.
    return VideoAssembler._build_segments(stub, plan, source_duration=120.0)


class TestBuildSegmentsTailExtension:
    def test_non_last_segment_extended_by_crossfade_duration(self):
        segments = _call_build_segments(crossfade=0.2, fps=30.0)
        # Two clips → two segments. Non-last segment (index 0) SHALL span
        # core 4.0s + crossfade tail 6/30 s = 4.2s. Last segment (index 1)
        # SHALL remain 4.0s (no tail).
        assert len(segments) == 2
        start0, dur0, idx0 = segments[0]
        start1, dur1, idx1 = segments[1]
        assert idx0 == 0 and idx1 == 1
        assert start0 == 0.0
        assert start1 == 4.0
        # 4.0s core + 6 frames at 30 fps = 4.0 + 0.2 = 4.2s.
        assert dur0 == 0.2 + 4.0

    def test_cut_plan_segments_do_not_extend(self):
        stub = _AsmStub(crossfade=0.0, fps=30.0)
        stub.config.transition_style = TransitionStyle.HARD_CUT
        # HARD_CUT ⇒ xfade_frames=0, segments SHALL be core-length only.
        plan = _plan(crossfade=0.0)
        plan.transition_style = TransitionStyle.HARD_CUT.value
        segments = VideoAssembler._build_segments(stub, plan, source_duration=120.0)
        assert len(segments) == 2
        # Both segments are exactly 4.0s (core).
        assert segments[0][1] == 4.0
        assert segments[1][1] == 4.0
