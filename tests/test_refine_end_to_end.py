"""End-to-end integration test for the refine-plate-box-fit flow.

Exercises the worker → review-dialog → save-plates pipeline on a synthetic
in-memory video (no real MP4 needed), verifying that accepted refinements
round-trip through persistence with ``angle`` intact.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.plate.blur import apply_blur_to_frame
from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.plate.refiner import RefinementResult
from trailvideocut.plate.storage import load_plates, save_plates
from trailvideocut.ui.plate_refine_dialog import RefinementEntry
from trailvideocut.ui.workers import PlateRefineWorker


class _SignalCollector:
    def __init__(self, worker: PlateRefineWorker):
        self.finished: list = []
        self.cancelled: list = []
        self.error: list = []
        worker.finished.connect(lambda r: self.finished.append(r))
        worker.cancelled.connect(lambda: self.cancelled.append(True))
        worker.error.connect(lambda s: self.error.append(s))


def test_refine_results_persist_with_angle(qapp, tmp_path):
    """Run the worker with a refiner that emits oriented boxes, simulate the
    user accepting both refinements, write the mutated ClipPlateData to a
    sidecar, load it, and verify the angles survived the round trip.
    """
    video = tmp_path / "fake.mp4"
    video.touch()

    initial = {
        0: ClipPlateData(
            clip_index=0,
            detections={
                10: [PlateBox(0.1, 0.2, 0.1, 0.05, 0.9)],
                11: [PlateBox(0.1, 0.2, 0.1, 0.05, 0.9)],
            },
        ),
    }

    def _refiner(frame, box, cfg=None):
        return RefinementResult(
            box=PlateBox(
                x=box.x + 0.005, y=box.y + 0.005,
                w=box.w - 0.01, h=box.h - 0.01,
                confidence=box.confidence, manual=box.manual,
                angle=12.0,
            ),
            confidence=0.85,
            method="oriented",
        )

    def _frame_provider(frame_no: int):
        return np.zeros((20, 20, 3), dtype=np.uint8)

    frames_and_boxes = [
        (10, [(0, initial[0].detections[10][0])]),
        (11, [(0, initial[0].detections[11][0])]),
    ]
    w = PlateRefineWorker(
        video_path=str(video),
        frames_and_boxes=frames_and_boxes,
        refine_fn=_refiner,
        frame_provider=_frame_provider,
    )
    c = _SignalCollector(w)
    w._run_impl()

    assert c.cancelled == []
    assert c.error == []
    assert len(c.finished) == 1
    results = c.finished[0]
    assert len(results) == 2

    # Simulate the user accepting all refinements. Construct
    # RefinementEntry-shaped data and apply to the ClipPlateData exactly like
    # _show_refine_review_dialog does.
    entries = [
        RefinementEntry(
            frame_no=row[0], box_idx=row[1], before=row[2], after=row[3],
            confidence=row[4], method=row[5], accepted=True,
        )
        for row in results
    ]
    for entry in entries:
        boxes = initial[0].detections[entry.frame_no]
        boxes[entry.box_idx] = entry.after

    # Persist and round-trip.
    save_plates(video, initial)
    loaded = load_plates(video)
    for frame_no in (10, 11):
        box = loaded[0].detections[frame_no][0]
        assert box.angle == pytest.approx(12.0)
        assert box.confidence == pytest.approx(0.9)  # detection conf preserved


def test_oriented_blur_masks_rotated_polygon(qapp):
    """Sanity: apply_blur_to_frame with an oriented box from the refine flow
    produces a mask that only blurs pixels inside the rotated quadrilateral.

    Guards the contract that accepted refinements from this feature flow
    directly into the existing blur/export path without further massaging.
    """
    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    # Small high-contrast tile so the blur's effect is locally measurable.
    frame[80:120, 180:220] = 255
    original = frame.copy()

    refined = PlateBox(x=0.4, y=0.4, w=0.2, h=0.2, angle=20.0)
    apply_blur_to_frame(frame, [refined])

    # Somewhere inside the rotated polygon should have changed.
    assert not np.array_equal(frame, original)
    # Envelope-corner pixel should still be untouched (strictly outside the
    # rotated polygon).
    env_x, env_y, env_w, env_h = refined.aabb_envelope()
    ex = int(round(env_x * 400))
    ey = int(round(env_y * 200))
    assert np.array_equal(frame[ey + 1, ex + 1], original[ey + 1, ex + 1])
