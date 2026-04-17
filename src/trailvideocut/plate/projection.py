"""Linear motion projection for manually-added plate boxes.

Pure, Qt-free helper used by the review UI to place a new manual plate box
close to where the plate actually is on the current frame, based on recent
detections on either side of it.
"""

from collections.abc import Mapping

from trailvideocut.plate.models import PlateBox


def _center(box: PlateBox) -> tuple[float, float]:
    return (box.x + box.w / 2, box.y + box.h / 2)


def _clamp_box(cx: float, cy: float, w: float, h: float) -> PlateBox:
    x = cx - w / 2
    y = cy - h / 2
    # Size first, then position, so a box smaller than the frame always fits.
    w = max(0.0, min(1.0, w))
    h = max(0.0, min(1.0, h))
    x = max(0.0, min(1.0 - w, x))
    y = max(0.0, min(1.0 - h, y))
    return PlateBox(x=x, y=y, w=w, h=h)


def _pick_samples(
    frames: list[int],
    current_frame: int,
) -> tuple[int, int] | None:
    """Pick (older, newer) reference frames in preference order.

    1. Two closest prior detections.
    2. One prior + one next (closest on each side).
    3. Two closest next detections.
    """
    priors = [f for f in frames if f < current_frame]
    nexts = [f for f in frames if f > current_frame]

    if len(priors) >= 2:
        # Closest two priors, ordered older → newer.
        p_sorted = sorted(priors, reverse=True)[:2]
        return (p_sorted[1], p_sorted[0])
    if priors and nexts:
        return (max(priors), min(nexts))
    if len(nexts) >= 2:
        n_sorted = sorted(nexts)[:2]
        return (n_sorted[0], n_sorted[1])
    return None


def project_manual_box(
    detections: Mapping[int, list[PlateBox]],
    current_frame: int,
    *,
    max_window: int = 60,
) -> PlateBox | None:
    """Project a manual plate box onto *current_frame* from recent detections.

    Uses two reference samples (preference: two prior, prior+next, two next) to
    linearly project the box center to the current frame. Size is taken from
    the sample whose frame is closest to *current_frame*. The result is clamped
    to stay fully inside the [0, 1] normalized frame.

    Returns ``None`` when:
      - fewer than two reference detections with non-empty box lists exist, or
      - either chosen reference frame is further than *max_window* frames from
        *current_frame*.

    The returned box carries geometry only (``confidence=0.0``, ``manual=False``);
    the caller is responsible for setting ``manual=True`` before storing it.
    """
    usable_frames = [f for f, boxes in detections.items() if boxes]
    pair = _pick_samples(usable_frames, current_frame)
    if pair is None:
        return None

    older, newer = pair
    if abs(older - current_frame) > max_window or abs(newer - current_frame) > max_window:
        return None

    older_box = detections[older][0]
    newer_box = detections[newer][0]

    ox, oy = _center(older_box)
    nx, ny = _center(newer_box)

    # Linear interpolation / extrapolation of the center.
    span = newer - older  # guaranteed non-zero by _pick_samples
    t = (current_frame - older) / span
    cx = ox + (nx - ox) * t
    cy = oy + (ny - oy) * t

    # Size from the reference frame closest to current_frame.
    nearest_box = newer_box if abs(newer - current_frame) <= abs(older - current_frame) else older_box

    return _clamp_box(cx, cy, nearest_box.w, nearest_box.h)
