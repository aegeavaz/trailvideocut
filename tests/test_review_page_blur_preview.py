"""Blur-preview tiles SHALL cover the AABB envelope of oriented plates, so
the blurred rotated patch is faithfully drawn on the overlay (not a square
slice of it).

fix-plate-box-handlers / group 8.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.editor.models import EditDecision
from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.review_page import ReviewPage


def _make_page(qapp, frame: np.ndarray) -> ReviewPage:
    page = ReviewPage()
    clip = EditDecision(
        beat_index=0,
        source_start=0.0, source_end=5.0,
        target_start=0.0, target_end=5.0,
        interest_score=1.0,
    )
    page._timeline.set_data([clip], video_duration=5.0)
    page._timeline.select_clip(0)
    page._video_path = "/fake.mp4"
    page._player.frame_at = lambda *_: 0
    page._player.grab_current_frame = lambda: frame.copy()
    page._plate_overlay.set_current_frame(0)
    page._plate_overlay.setVisible(True)
    page._btn_preview_blur.setChecked(True)
    return page


class TestBlurPreviewTileRect:
    def test_oriented_plate_tile_covers_envelope(self, qapp):
        """On a frame with a rotated plate, the blur tile registered on the
        overlay must span the box's AABB envelope — not the plate-aligned
        (x, y, w, h) — so the rotated blur is rendered faithfully."""
        frame = np.full((200, 400, 3), 128, dtype=np.uint8)
        box = PlateBox(x=0.4, y=0.45, w=0.2, h=0.05, angle=20.0, manual=True)
        page = _make_page(qapp, frame)
        try:
            page._plate_data[0] = ClipPlateData(
                clip_index=0, detections={0: [box]},
            )
            page._plate_overlay.set_clip_data(page._plate_data[0])

            page._update_blur_preview()

            tiles = page._plate_overlay._blur_tiles
            assert len(tiles) == 1
            (nx, ny, nw, nh), _pixmap = tiles[0]

            env_x, env_y, env_w, env_h = box.aabb_envelope()
            assert (nx, ny, nw, nh) != pytest.approx(
                (box.x, box.y, box.w, box.h), abs=1e-9,
            ), "tile still uses the plate-aligned rect, not the envelope"
            assert nx == pytest.approx(env_x, abs=1e-9)
            assert ny == pytest.approx(env_y, abs=1e-9)
            assert nw == pytest.approx(env_w, abs=1e-9)
            assert nh == pytest.approx(env_h, abs=1e-9)
        finally:
            page.close()

    def test_axis_aligned_plate_tile_matches_box(self, qapp):
        """For angle==0 the envelope and the plate-aligned rect coincide;
        behaviour must be pixel-identical to the pre-feature preview."""
        frame = np.full((200, 400, 3), 128, dtype=np.uint8)
        box = PlateBox(x=0.3, y=0.4, w=0.2, h=0.1, angle=0.0, manual=True)
        page = _make_page(qapp, frame)
        try:
            page._plate_data[0] = ClipPlateData(
                clip_index=0, detections={0: [box]},
            )
            page._plate_overlay.set_clip_data(page._plate_data[0])

            page._update_blur_preview()

            tiles = page._plate_overlay._blur_tiles
            assert len(tiles) == 1
            (nx, ny, nw, nh), _pixmap = tiles[0]
            assert nx == pytest.approx(box.x, abs=1e-9)
            assert ny == pytest.approx(box.y, abs=1e-9)
            assert nw == pytest.approx(box.w, abs=1e-9)
            assert nh == pytest.approx(box.h, abs=1e-9)
        finally:
            page.close()
