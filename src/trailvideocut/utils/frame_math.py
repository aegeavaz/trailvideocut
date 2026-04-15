"""Frame/time conversion helpers shared between UI and tests.

Semantics: frame numbers are integer source-frame indices (matching OpenCV /
FFmpeg). ``position_to_frame`` uses truncation so the frame number of a
position always equals the frame the decoder actually displays at that time.
``frame_to_position_ms`` uses ceil so the target milliseconds land just past
the frame boundary; this guarantees that ``position_to_frame`` after a
millisecond round-trip returns the intended frame even for non-integer FPS.
"""

import math


def position_to_frame(position_s: float, fps: float) -> int:
    """Convert a time position (seconds) to the source frame index at that time.

    A tiny epsilon absorbs float round-trip drift (e.g. ``4100/1000 * 30``
    evaluating to ``122.9999…`` instead of ``123.0``) without crossing any
    real frame boundary — epsilon is orders of magnitude below any plausible
    frame duration.
    """
    return int(position_s * fps + 1e-9)


def frame_to_position_ms(frame: int, fps: float) -> int:
    """Convert a frame index to a millisecond position inside that frame."""
    if frame <= 0:
        return 0
    return math.ceil(frame * 1000.0 / fps)
