"""Editor package — edit decisions, cut plans, and plate-window helpers."""

from trailvideocut.editor.models import (
    CutPlan,
    EditDecision,
    clip_frame_window,
    tail_frames,
)

__all__ = [
    "CutPlan",
    "EditDecision",
    "clip_frame_window",
    "tail_frames",
]
