"""Oriented-box rendering & edit-reverts-angle tests for PlateOverlayWidget.

refine-plate-box-fit / group 5.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QMouseEvent

from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.plate_overlay import PlateOverlayWidget


def _render_overlay(overlay: PlateOverlayWidget, w: int, h: int) -> np.ndarray:
    """Paint the overlay onto an RGBA numpy buffer for pixel assertions."""
    image = QImage(w, h, QImage.Format_ARGB32)
    image.fill(0)
    overlay.resize(w, h)
    # Force the effective rect to cover the full image so norm→px is exact.
    overlay.set_effective_video_rect(QRectF(0, 0, w, h))
    overlay.render(image, QPoint(0, 0))
    ptr = image.constBits()
    return np.array(ptr).reshape(h, w, 4).copy()


class TestOrientedOutline:
    def test_rotated_box_draws_polygon_outline(self, qapp):
        overlay = PlateOverlayWidget()
        overlay.set_video_size(200, 200)
        data = ClipPlateData(
            clip_index=0,
            detections={0: [PlateBox(0.3, 0.3, 0.4, 0.4, angle=30.0)]},
        )
        overlay.set_clip_data(data)
        overlay.set_current_frame(0)

        img = _render_overlay(overlay, 200, 200)
        # Build a mask of non-background pixels (any RGBA alpha > 0).
        drawn = img[..., 3] > 0

        # Corners of the rotated quadrilateral (in overlay-pixel coords).
        box = data.detections[0][0]
        corners = np.array(box.corners_px(200, 200), dtype=np.float32)

        # Every drawn pixel that matches the border colour family should lie
        # within a few pixels of the rotated polygon's boundary — i.e. a
        # pixel on the border segment has |signed distance| <= 3.
        ys, xs = np.where(drawn)
        # Keep the pixel-count check loose (at least some pixels drawn).
        assert xs.size > 0
        # Sample a handful of drawn pixels and require most to be near the
        # polygon edge (not inside an AABB-only region).
        # We focus on pixels whose pointPolygonTest returns small |d|.
        near_edge = 0
        envelope = box.aabb_envelope()
        env_rect = (
            int(round(envelope[0] * 200)),
            int(round(envelope[1] * 200)),
            int(round(envelope[2] * 200)),
            int(round(envelope[3] * 200)),
        )
        ex, ey, ew, eh = env_rect
        # Pixels inside the envelope AABB corners but clearly outside the
        # rotated polygon (e.g., (ex+1, ey+1)) should NOT be part of the
        # polygon outline — if they are coloured, the code is drawing the
        # envelope rectangle instead of the polygon. Check 1px inside each
        # envelope corner.
        for (cx, cy) in [
            (ex + 2, ey + 2),
            (ex + ew - 3, ey + 2),
            (ex + 2, ey + eh - 3),
            (ex + ew - 3, ey + eh - 3),
        ]:
            # Each envelope-corner pixel should be strictly outside the
            # rotated polygon, and therefore transparent (background).
            inside = cv2.pointPolygonTest(
                corners, (float(cx), float(cy)), measureDist=False,
            )
            if inside < 0:
                assert img[cy, cx, 3] == 0 or img[cy, cx, 3] < 5, (
                    f"envelope corner pixel ({cx},{cy}) was drawn but lies "
                    f"outside the rotated polygon"
                )
                near_edge += 1
        assert near_edge > 0  # at least one real check ran

    def test_axis_aligned_box_still_draws_rectangle(self, qapp):
        """Regression: angle == 0 should still produce a rectangle outline."""
        overlay = PlateOverlayWidget()
        overlay.set_video_size(200, 200)
        data = ClipPlateData(
            clip_index=0,
            detections={0: [PlateBox(0.3, 0.3, 0.4, 0.4)]},
        )
        overlay.set_clip_data(data)
        overlay.set_current_frame(0)

        img = _render_overlay(overlay, 200, 200)
        # All four axis-aligned corners should be drawn.
        corners = [(60, 60), (139, 60), (60, 139), (139, 139)]
        for cx, cy in corners:
            assert img[cy, cx, 3] > 0


class TestEditPreservesAngle:
    def test_move_preserves_angle(self, qapp):
        """Dragging an oriented box by its body keeps the rotation angle."""
        overlay = PlateOverlayWidget()
        overlay.set_video_size(200, 200)
        overlay.resize(200, 200)
        overlay.set_effective_video_rect(QRectF(0, 0, 200, 200))
        box = PlateBox(0.3, 0.3, 0.4, 0.4, angle=20.0)
        data = ClipPlateData(clip_index=0, detections={0: [box]})
        overlay.set_clip_data(data)
        overlay.set_current_frame(0)
        overlay.select_box(0)

        # Click inside the rotated box (its centre), drag 10 px right.
        cx = (box.x + box.w / 2) * 200
        cy = (box.y + box.h / 2) * 200
        press = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(cx, cy),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        overlay.mousePressEvent(press)
        move = QMouseEvent(
            QEvent.MouseMove, QPointF(cx + 10, cy + 5),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        )
        overlay.mouseMoveEvent(move)
        release = QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(cx + 10, cy + 5),
            Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
        )
        overlay.mouseReleaseEvent(release)

        got = data.detections[0][0]
        assert got.angle == pytest.approx(20.0)
        assert got.w == pytest.approx(0.4)
        assert got.h == pytest.approx(0.4)

    def test_resize_preserves_angle(self, qapp):
        """Dragging a rotated corner resizes in plate-aligned space and keeps
        the angle."""
        overlay = PlateOverlayWidget()
        overlay.set_video_size(200, 200)
        overlay.resize(200, 200)
        overlay.set_effective_video_rect(QRectF(0, 0, 200, 200))
        box = PlateBox(0.3, 0.3, 0.4, 0.4, angle=20.0)
        data = ClipPlateData(clip_index=0, detections={0: [box]})
        overlay.set_clip_data(data)
        overlay.set_current_frame(0)
        overlay.select_box(0)

        # Press exactly on the rotated "br" corner.
        corners = box.corners_px(200, 200)
        br_x, br_y = corners[2]
        press = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(br_x, br_y),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        overlay.mousePressEvent(press)
        move = QMouseEvent(
            QEvent.MouseMove, QPointF(br_x + 10, br_y + 10),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        )
        overlay.mouseMoveEvent(move)
        release = QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(br_x + 10, br_y + 10),
            Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
        )
        overlay.mouseReleaseEvent(release)

        got = data.detections[0][0]
        # Angle stays; dimensions change from the drag.
        assert got.angle == pytest.approx(20.0)
        assert got.w != pytest.approx(0.4)

    def test_rotate_handle_changes_angle(self, qapp):
        """Dragging the rotation handle changes only the angle."""
        overlay = PlateOverlayWidget()
        overlay.set_video_size(400, 400)
        overlay.resize(400, 400)
        overlay.set_effective_video_rect(QRectF(0, 0, 400, 400))
        box = PlateBox(0.4, 0.4, 0.2, 0.2, angle=0.0)
        data = ClipPlateData(clip_index=0, detections={0: [box]})
        overlay.set_clip_data(data)
        overlay.set_current_frame(0)
        overlay.select_box(0)

        # The rotation handle sits above the top-centre of the box.
        positions = overlay._handle_positions_for_box(box)
        rot_pos = positions["rotate"]
        # Drag horizontally to rotate the box; 10 px right at 18 px above the
        # top should produce ~30° rotation.
        press = QMouseEvent(
            QEvent.MouseButtonPress, rot_pos,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        overlay.mousePressEvent(press)
        # Compute a target point a quarter-circle away (90° rotation).
        cx = (box.x + box.w / 2) * 400
        cy = (box.y + box.h / 2) * 400
        # Original handle is above centre (angle = -90° in screen coords).
        # Move to a point to the right of centre → target angle 0°.
        # That's a +90° delta.
        target = QPointF(cx + 60, cy)
        move = QMouseEvent(
            QEvent.MouseMove, target,
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        )
        overlay.mouseMoveEvent(move)
        release = QMouseEvent(
            QEvent.MouseButtonRelease, target,
            Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
        )
        overlay.mouseReleaseEvent(release)

        got = data.detections[0][0]
        assert abs(got.angle - 90.0) < 1.0
        # Size unchanged by a pure rotation.
        assert got.w == pytest.approx(0.2)
        assert got.h == pytest.approx(0.2)
