"""Geometry & edit tests for the plate-overlay handle/outline/hit-test/resize.

fix-plate-box-handlers. The existing ``test_plate_overlay_oriented.py`` runs
on a square (200x200) canvas, which hides the non-square aspect-ratio
distortion. These tests deliberately use a 1920x1080 effective rect so the
rotation-in-pixel-space fixes are exercised.

Test pattern follows ``tests/conftest.py``'s session-scoped ``qapp`` fixture
and the ``set_effective_video_rect`` shortcut used throughout
``test_plate_overlay_oriented.py``.
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent

from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.plate_overlay import PlateOverlayWidget


VW, VH = 1920, 1080


def _make_overlay(qapp) -> PlateOverlayWidget:
    overlay = PlateOverlayWidget()
    overlay.set_video_size(VW, VH)
    overlay.resize(VW, VH)
    overlay.set_effective_video_rect(QRectF(0, 0, VW, VH))
    return overlay


def _install_box(overlay: PlateOverlayWidget, box: PlateBox) -> ClipPlateData:
    data = ClipPlateData(clip_index=0, detections={0: [box]})
    overlay.set_clip_data(data)
    overlay.set_current_frame(0)
    overlay.select_box(0)
    return data


def _edge_length(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _is_rectangle(corners: list[QPointF]) -> tuple[bool, str]:
    """Return (True, "") if corners TL→TR→BR→BL form a rectangle in widget
    pixel space, else (False, reason)."""
    if len(corners) != 4:
        return False, f"expected 4 corners, got {len(corners)}"
    tl, tr, br, bl = corners
    top = _edge_length(tl, tr)
    right = _edge_length(tr, br)
    bottom = _edge_length(br, bl)
    left = _edge_length(bl, tl)
    if abs(top - bottom) > 1e-3:
        return False, f"top {top:.3f} vs bottom {bottom:.3f}"
    if abs(left - right) > 1e-3:
        return False, f"left {left:.3f} vs right {right:.3f}"
    # Dot product of adjacent edges ~ 0 → 90°.
    e_top = (tr.x() - tl.x(), tr.y() - tl.y())
    e_right = (br.x() - tr.x(), br.y() - tr.y())
    dot = e_top[0] * e_right[0] + e_top[1] * e_right[1]
    if abs(dot) > 1e-3:
        return False, f"TL-TR·TR-BR dot = {dot:.3f} (not perpendicular)"
    return True, ""


class TestOrientedCornerHelper:
    def test_corners_form_a_rectangle_on_non_square_video(self, qapp):
        """`_oriented_corners_widget` returns four widget-pixel points that
        form a rectangle, even when the video's pixel width and height
        differ (which is where the old normalized-space rotation broke)."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.4, y=0.45, w=0.2, h=0.05, angle=20.0)
        _install_box(overlay, box)

        corners = overlay._oriented_corners_widget(box)
        ok, why = _is_rectangle(corners)
        assert ok, why

        # Sanity: edge lengths match pixel-space half-extents.
        expected_w_px = box.w * VW
        expected_h_px = box.h * VH
        top = _edge_length(corners[0], corners[1])
        right = _edge_length(corners[1], corners[2])
        assert top == pytest.approx(expected_w_px, abs=1e-3)
        assert right == pytest.approx(expected_h_px, abs=1e-3)

    def test_axis_aligned_corners_match_envelope(self, qapp):
        """Regression: angle==0 produces the same corners as before the
        pixel-space refactor."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.3, y=0.4, w=0.2, h=0.1, angle=0.0)
        _install_box(overlay, box)

        corners = overlay._oriented_corners_widget(box)
        assert corners[0].x() == pytest.approx(0.3 * VW)
        assert corners[0].y() == pytest.approx(0.4 * VH)
        assert corners[2].x() == pytest.approx(0.5 * VW)
        assert corners[2].y() == pytest.approx(0.5 * VH)


class TestHandlesOnOutline:
    def test_handle_anchors_coincide_with_corner_helper(self, qapp):
        """Every corner/edge resize-handle position sits exactly on the
        outline that `_oriented_corners_widget` returns."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.4, y=0.45, w=0.2, h=0.05, angle=20.0)
        _install_box(overlay, box)

        corners = overlay._oriented_corners_widget(box)
        tl, tr, br, bl = corners
        positions = overlay._handle_positions_for_box(box)

        # Corners.
        for name, expected in (("tl", tl), ("tr", tr), ("br", br), ("bl", bl)):
            got = positions[name]
            assert got.x() == pytest.approx(expected.x(), abs=1e-3), name
            assert got.y() == pytest.approx(expected.y(), abs=1e-3), name

        # Edge midpoints.
        def _mid(a: QPointF, b: QPointF) -> tuple[float, float]:
            return ((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0)

        for name, (a, b) in (
            ("t", (tl, tr)),
            ("b", (bl, br)),
            ("l", (tl, bl)),
            ("r", (tr, br)),
        ):
            mx, my = _mid(a, b)
            got = positions[name]
            assert got.x() == pytest.approx(mx, abs=1e-3), name
            assert got.y() == pytest.approx(my, abs=1e-3), name


class TestPointInRotatedBox:
    def test_envelope_corner_outside_rotated_body(self, qapp):
        """A click inside the AABB envelope but outside the rotated
        rectangle must NOT register as a hit."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.4, y=0.45, w=0.2, h=0.1, angle=30.0)
        _install_box(overlay, box)

        env_x, env_y, env_w, env_h = box.aabb_envelope()
        # A point 2 px inside the envelope's top-left — that lies in the
        # transparent triangle outside the rotated body.
        envelope_tl = QPointF(env_x * VW + 2.0, env_y * VH + 2.0)
        assert overlay._point_in_box(envelope_tl, box) is False

    def test_point_just_inside_rotated_corner_is_hit(self, qapp):
        """A point 5 px inside the rotated TL corner (along the diagonal
        toward the centre) lies clearly inside the rotated body. The
        buggy normalized-space hit-test reports it outside because the
        box's local half-widths (0.1, 0.05) on a 1920x1080 canvas correspond
        to different pixel distances; the correct pixel-space test reports
        it inside."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.4, y=0.45, w=0.2, h=0.1, angle=30.0)
        _install_box(overlay, box)

        # Pixel-space TL corner.
        rad = math.radians(box.angle)
        cx_px = (box.x + box.w / 2) * VW
        cy_px = (box.y + box.h / 2) * VH
        hw, hh = box.w * VW / 2, box.h * VH / 2
        tl_px = QPointF(
            cx_px + (-hw) * math.cos(rad) - (-hh) * math.sin(rad),
            cy_px + (-hw) * math.sin(rad) + (-hh) * math.cos(rad),
        )
        dx, dy = cx_px - tl_px.x(), cy_px - tl_px.y()
        length = math.hypot(dx, dy)
        probe = QPointF(tl_px.x() + 5 * dx / length, tl_px.y() + 5 * dy / length)

        assert overlay._point_in_box(probe, box) is True

    def test_centre_is_inside_rotated_body(self, qapp):
        """The box centre must register as a hit."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.4, y=0.45, w=0.2, h=0.1, angle=30.0)
        _install_box(overlay, box)

        cx_px = (box.x + box.w / 2) * VW
        cy_px = (box.y + box.h / 2) * VH
        assert overlay._point_in_box(QPointF(cx_px, cy_px), box) is True


def _drag(overlay: PlateOverlayWidget, start: QPointF, end: QPointF) -> None:
    press = QMouseEvent(
        QEvent.MouseButtonPress, start,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    overlay.mousePressEvent(press)
    move = QMouseEvent(
        QEvent.MouseMove, end,
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
    )
    overlay.mouseMoveEvent(move)
    release = QMouseEvent(
        QEvent.MouseButtonRelease, end,
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
    )
    overlay.mouseReleaseEvent(release)


class TestResizePreservesRectangleOnNonSquareVideo:
    def test_br_corner_drag_lands_at_mouse_and_preserves_angle(self, qapp):
        """Dragging the `br` corner on a non-square canvas must move the
        pixel-space BR corner of the box onto the mouse target, while
        preserving the angle and the TL anchor."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.4, y=0.45, w=0.2, h=0.05, angle=20.0)
        data = _install_box(overlay, box)

        positions_before = overlay._handle_positions_for_box(box)
        br_before = positions_before["br"]
        tl_before = positions_before["tl"]
        target = QPointF(br_before.x() + 40, br_before.y() + 5)
        _drag(overlay, br_before, target)

        got = data.detections[0][0]
        assert got.angle == pytest.approx(20.0)

        positions_after = overlay._handle_positions_for_box(got)
        br_after = positions_after["br"]
        tl_after = positions_after["tl"]
        # BR must land at the mouse target (within 1 px — normalize/round).
        assert br_after.x() == pytest.approx(target.x(), abs=1.0)
        assert br_after.y() == pytest.approx(target.y(), abs=1.0)
        # TL anchor must stay fixed in pixel coords.
        assert tl_after.x() == pytest.approx(tl_before.x(), abs=1.0)
        assert tl_after.y() == pytest.approx(tl_before.y(), abs=1.0)

    def test_r_edge_drag_keeps_height_and_opposite_edge_anchored(self, qapp):
        """Dragging the `r` edge moves only the plate-horizontal extent; the
        plate-vertical size stays and the opposite edge midpoint stays put
        in pixel space."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.4, y=0.45, w=0.2, h=0.05, angle=20.0)
        data = _install_box(overlay, box)

        positions = overlay._handle_positions_for_box(box)
        left_mid_before = QPointF(positions["l"].x(), positions["l"].y())
        h_before = box.h
        r = positions["r"]
        _drag(overlay, r, QPointF(r.x() + 30, r.y()))

        got = data.detections[0][0]
        assert got.angle == pytest.approx(20.0)
        assert got.h == pytest.approx(h_before, abs=1e-4), (
            f"h changed: {h_before} → {got.h}"
        )

        # Left-edge midpoint must remain at its pre-drag pixel position.
        positions_after = overlay._handle_positions_for_box(got)
        left_mid_after = positions_after["l"]
        assert left_mid_after.x() == pytest.approx(
            left_mid_before.x(), abs=0.5,
        )
        assert left_mid_after.y() == pytest.approx(
            left_mid_before.y(), abs=0.5,
        )

    def test_axis_aligned_br_drag_matches_plain_math(self, qapp):
        """Regression for angle==0: dragging br by (+40, +20) on a 1920x1080
        canvas grows w by 40/1920 and h by 20/1080 (since the reference is
        the TL corner)."""
        overlay = _make_overlay(qapp)
        box = PlateBox(x=0.3, y=0.4, w=0.2, h=0.1, angle=0.0)
        data = _install_box(overlay, box)

        positions = overlay._handle_positions_for_box(box)
        br = positions["br"]
        _drag(overlay, br, QPointF(br.x() + 40, br.y() + 20))

        got = data.detections[0][0]
        assert got.x == pytest.approx(0.3)
        assert got.y == pytest.approx(0.4)
        assert got.w == pytest.approx(0.2 + 40 / VW, abs=1e-4)
        assert got.h == pytest.approx(0.1 + 20 / VH, abs=1e-4)
        assert got.angle == pytest.approx(0.0)
