"""Tests for PlateRefineWorker (refine-plate-box-fit group 6).

The worker exposes a ``_run_impl`` we can invoke synchronously with an
injected ``refine_fn`` + ``frame_provider`` to cover cancel/progress/signal
logic without spinning up a QThread or decoding a real video.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication

from trailvideocut.plate.models import PlateBox
from trailvideocut.plate.refiner import RefinementResult
from trailvideocut.ui.workers import PlateRefineWorker


def _dummy_refiner(frame, box, cfg=None):
    # Produce a tighter box and a flat "oriented" method marker for the tests
    # to assert against.
    return RefinementResult(
        box=PlateBox(box.x + 0.01, box.y + 0.01, box.w - 0.02, box.h - 0.02,
                     confidence=box.confidence, manual=box.manual, angle=0.0),
        confidence=0.75,
        method="aabb",
    )


def _fake_frame_provider(frame_no: int) -> np.ndarray:
    return np.zeros((10, 10, 3), dtype=np.uint8)


class _SignalCollector:
    """Record emissions by binding to the worker's signals."""

    def __init__(self, worker: PlateRefineWorker):
        self.progress: list[tuple[int, int]] = []
        self.frames: list[tuple] = []
        self.finished: list = []
        self.cancelled: list[bool] = []
        self.error: list[str] = []
        worker.progress.connect(lambda d, t: self.progress.append((d, t)))
        worker.frame_done.connect(
            lambda *a: self.frames.append(tuple(a)),
        )
        worker.finished.connect(lambda r: self.finished.append(r))
        worker.cancelled.connect(lambda: self.cancelled.append(True))
        worker.error.connect(lambda s: self.error.append(s))


class TestSignalOrdering:
    def test_progress_bracketed_around_frame_done(self, qapp):
        _ = QCoreApplication.instance() or qapp
        frames_and_boxes = [
            (10, [(0, PlateBox(0.1, 0.1, 0.1, 0.05, confidence=0.9))]),
            (11, [
                (0, PlateBox(0.1, 0.1, 0.1, 0.05, confidence=0.9)),
                (1, PlateBox(0.3, 0.3, 0.1, 0.05, confidence=0.8, manual=True)),
            ]),
        ]
        w = PlateRefineWorker(
            video_path="/fake",
            frames_and_boxes=frames_and_boxes,
            refine_fn=_dummy_refiner,
            frame_provider=_fake_frame_provider,
        )
        c = _SignalCollector(w)
        w._run_impl()

        # Initial progress is (0, total) where total = 3 boxes.
        assert c.progress[0] == (0, 3)
        # Final progress reaches (3, 3).
        assert c.progress[-1] == (3, 3)
        # frame_done emitted once per box.
        assert len(c.frames) == 3
        # finished carries the full results list.
        assert len(c.finished) == 1
        assert len(c.finished[0]) == 3
        # Manual flag is preserved from the input box through the worker.
        assert c.frames[-1][2].manual is True
        # cancelled not fired.
        assert c.cancelled == []
        assert c.error == []

    def test_empty_workload(self, qapp):
        _ = QCoreApplication.instance() or qapp
        w = PlateRefineWorker(
            video_path="/fake",
            frames_and_boxes=[],
            refine_fn=_dummy_refiner,
            frame_provider=_fake_frame_provider,
        )
        c = _SignalCollector(w)
        w._run_impl()
        assert c.progress == [(0, 0)]
        assert c.frames == []
        assert c.finished == [[]]
        assert c.cancelled == []


class TestCancellation:
    def test_cancel_before_start_emits_cancelled(self, qapp):
        _ = QCoreApplication.instance() or qapp
        w = PlateRefineWorker(
            video_path="/fake",
            frames_and_boxes=[
                (10, [(0, PlateBox(0.1, 0.1, 0.1, 0.05))]),
                (11, [(0, PlateBox(0.1, 0.1, 0.1, 0.05))]),
            ],
            refine_fn=_dummy_refiner,
            frame_provider=_fake_frame_provider,
        )
        c = _SignalCollector(w)
        w.stop()
        w._run_impl()
        assert c.cancelled == [True]
        assert c.finished == []

    def test_cancel_mid_run(self, qapp):
        _ = QCoreApplication.instance() or qapp
        worker_ref: list[PlateRefineWorker] = []

        def _cancelling_refiner(frame, box, cfg=None):
            # Trigger cancel after the first box is refined.
            worker_ref[0].stop()
            return _dummy_refiner(frame, box, cfg)

        w = PlateRefineWorker(
            video_path="/fake",
            frames_and_boxes=[
                (10, [(0, PlateBox(0.1, 0.1, 0.1, 0.05))]),
                (11, [(0, PlateBox(0.2, 0.2, 0.1, 0.05))]),
            ],
            refine_fn=_cancelling_refiner,
            frame_provider=_fake_frame_provider,
        )
        worker_ref.append(w)
        c = _SignalCollector(w)
        w._run_impl()

        # First box refined, then cancellation caught.
        assert len(c.frames) == 1
        assert c.cancelled == [True]
        assert c.finished == []


class TestMissingFrames:
    def test_unreadable_frames_advance_progress(self, qapp):
        _ = QCoreApplication.instance() or qapp

        def _bad_provider(frame_no: int):
            return None  # simulate read failure

        w = PlateRefineWorker(
            video_path="/fake",
            frames_and_boxes=[
                (10, [(0, PlateBox(0.1, 0.1, 0.1, 0.05))]),
                (11, [(0, PlateBox(0.2, 0.2, 0.1, 0.05))]),
            ],
            refine_fn=_dummy_refiner,
            frame_provider=_bad_provider,
        )
        c = _SignalCollector(w)
        w._run_impl()

        # No boxes refined, but progress reached total and finished fires with
        # an empty result list.
        assert c.frames == []
        assert c.progress[-1] == (2, 2)
        assert c.finished == [[]]
