"""Tests for the plate overlay widget coordinate mapping and box manipulation."""

import pytest

from trailvideocut.plate.models import ClipPlateData, PlateBox


class TestPlateOverlayCoordinateMapping:
    """Test coordinate mapping logic without Qt (using raw calculations)."""

    def _video_rect(self, widget_w, widget_h, video_w, video_h):
        """Replicate PlateOverlayWidget._video_rect logic."""
        video_ar = video_w / video_h
        widget_ar = widget_w / widget_h

        if widget_ar > video_ar:
            display_h = widget_h
            display_w = display_h * video_ar
            x = (widget_w - display_w) / 2
            y = 0
        else:
            display_w = widget_w
            display_h = display_w / video_ar
            x = 0
            y = (widget_h - display_h) / 2

        return x, y, display_w, display_h

    def _norm_to_widget(self, nx, ny, nw, nh, widget_w, widget_h, video_w, video_h):
        vx, vy, vw, vh = self._video_rect(widget_w, widget_h, video_w, video_h)
        return (vx + nx * vw, vy + ny * vh, nw * vw, nh * vh)

    def test_16_9_video_in_16_9_widget(self):
        """No letterboxing — exact match."""
        x, y, w, h = self._video_rect(1600, 900, 1920, 1080)
        assert x == pytest.approx(0)
        assert y == pytest.approx(0)
        assert w == pytest.approx(1600)
        assert h == pytest.approx(900)

    def test_16_9_video_in_wider_widget(self):
        """Pillarboxing — black bars on sides."""
        x, y, w, h = self._video_rect(2000, 900, 1920, 1080)
        assert y == 0
        assert h == 900
        assert w == pytest.approx(900 * 1920 / 1080)
        assert x > 0  # pillarboxed

    def test_16_9_video_in_taller_widget(self):
        """Letterboxing — black bars top/bottom."""
        x, y, w, h = self._video_rect(1600, 1200, 1920, 1080)
        assert x == 0
        assert w == 1600
        assert h == pytest.approx(1600 / (1920 / 1080))
        assert y > 0  # letterboxed

    def test_normalized_box_center(self):
        """A box at (0.5, 0.5) with size 0 should map to center of video area."""
        x, y, w, h = self._norm_to_widget(0.5, 0.5, 0, 0, 1600, 900, 1920, 1080)
        assert x == pytest.approx(800)
        assert y == pytest.approx(450)

    def test_normalized_box_full_frame(self):
        """A box at (0, 0) with size (1, 1) should cover entire video area."""
        x, y, w, h = self._norm_to_widget(0, 0, 1, 1, 1600, 900, 1920, 1080)
        assert x == pytest.approx(0)
        assert y == pytest.approx(0)
        assert w == pytest.approx(1600)
        assert h == pytest.approx(900)


class TestClipPlateDataManipulation:
    """Test data operations without Qt."""

    def test_add_and_delete_box(self):
        data = ClipPlateData(clip_index=0)
        box = PlateBox(x=0.1, y=0.2, w=0.3, h=0.1, manual=True)
        data.detections[100] = [box]
        assert len(data.detections[100]) == 1

        data.detections[100].pop(0)
        assert len(data.detections[100]) == 0

    def test_preserve_manual_on_redetect(self):
        """Simulates re-detection: auto boxes replaced, manual preserved."""
        old_data = ClipPlateData(clip_index=0, detections={
            10: [PlateBox(0.1, 0.2, 0.3, 0.1, 0.9, False)],
            20: [
                PlateBox(0.1, 0.2, 0.3, 0.1, 0.8, False),
                PlateBox(0.5, 0.6, 0.2, 0.1, 0.0, True),  # manual
            ],
        })

        new_data = ClipPlateData(clip_index=0, detections={
            10: [PlateBox(0.15, 0.25, 0.3, 0.1, 0.95, False)],
            20: [PlateBox(0.12, 0.22, 0.3, 0.1, 0.85, False)],
        })

        # Merge: preserve manual boxes
        for frame, boxes in old_data.detections.items():
            manuals = [b for b in boxes if b.manual]
            if manuals:
                if frame in new_data.detections:
                    new_data.detections[frame].extend(manuals)
                else:
                    new_data.detections[frame] = manuals

        # Frame 10: new auto only
        assert len(new_data.detections[10]) == 1
        assert new_data.detections[10][0].confidence == pytest.approx(0.95)

        # Frame 20: new auto + preserved manual
        assert len(new_data.detections[20]) == 2
        assert any(b.manual for b in new_data.detections[20])

    def test_find_nearest_prior_box(self):
        """Test finding the nearest prior plate box."""
        data = ClipPlateData(clip_index=0, detections={
            10: [PlateBox(0.1, 0.2, 0.3, 0.1)],
            30: [PlateBox(0.5, 0.6, 0.2, 0.1)],
        })

        # From frame 25, should find frame 10's box
        current_frame = 25
        result = None
        for frame in sorted(data.detections.keys(), reverse=True):
            if frame < current_frame:
                boxes = data.detections[frame]
                if boxes:
                    result = boxes[0]
                    break

        assert result is not None
        assert result.x == pytest.approx(0.1)

        # From frame 35, should find frame 30's box
        current_frame = 35
        result = None
        for frame in sorted(data.detections.keys(), reverse=True):
            if frame < current_frame:
                result = data.detections[frame][0]
                break

        assert result is not None
        assert result.x == pytest.approx(0.5)


class TestFindNearestReferenceBox:
    """Test bidirectional reference box search logic (mirrors PlateOverlayWidget.find_nearest_reference_box)."""

    @staticmethod
    def _find_nearest_reference_box(data: ClipPlateData, current_frame: int) -> PlateBox | None:
        """Pure-function replica of the widget method for testing without Qt."""
        # Search backward
        for frame in sorted(data.detections.keys(), reverse=True):
            if frame < current_frame:
                boxes = data.detections[frame]
                if boxes:
                    return boxes[0]
        # Search forward
        for frame in sorted(data.detections.keys()):
            if frame > current_frame:
                boxes = data.detections[frame]
                if boxes:
                    return boxes[0]
        return None

    def test_returns_prior_frame_box(self):
        """Prior frame detection is preferred over later frames."""
        data = ClipPlateData(clip_index=0, detections={
            10: [PlateBox(0.1, 0.2, 0.3, 0.1)],
            30: [PlateBox(0.5, 0.6, 0.2, 0.1)],
        })
        result = self._find_nearest_reference_box(data, current_frame=25)
        assert result is not None
        assert result.x == pytest.approx(0.1)

    def test_returns_next_frame_box_when_no_prior(self):
        """Falls back to the next frame when no prior frame has detections."""
        data = ClipPlateData(clip_index=0, detections={
            20: [PlateBox(0.4, 0.5, 0.2, 0.08)],
            50: [PlateBox(0.6, 0.7, 0.1, 0.05)],
        })
        result = self._find_nearest_reference_box(data, current_frame=5)
        assert result is not None
        assert result.x == pytest.approx(0.4)

    def test_returns_none_when_no_detections(self):
        """Returns None when no frame has any detections."""
        data = ClipPlateData(clip_index=0, detections={})
        result = self._find_nearest_reference_box(data, current_frame=10)
        assert result is None


class TestPhoneFilterDebugOverlay:
    """Render and input-isolation tests for phone-zone debug rendering."""

    @staticmethod
    def _magenta_threshold(pixel) -> bool:
        """Pixel is QColor-like; true when the fill tint lies in the magenta quadrant."""
        return pixel.red() > pixel.green() and pixel.blue() > pixel.green()

    def _make_overlay(self, qapp):
        from trailvideocut.ui.plate_overlay import PlateOverlayWidget

        w = PlateOverlayWidget(None)
        w.set_video_size(1920, 1080)
        w.resize(1920, 1080)
        # Keep window hidden (WA_DontShowOnScreen) to avoid showing during tests.
        from PySide6.QtCore import Qt
        w.setAttribute(Qt.WA_DontShowOnScreen, True)
        w.show()
        qapp.processEvents()
        return w

    def test_set_phone_zones_renders_magenta_rect(self, qapp):
        from PySide6.QtGui import QImage

        overlay = self._make_overlay(qapp)
        overlay.set_phone_zones([(0.1, 0.2, 0.3, 0.4)])
        overlay.set_phone_zones_visible(True)
        qapp.processEvents()

        img = QImage(overlay.size(), QImage.Format_ARGB32)
        img.fill(0)
        overlay.render(img)

        # Center of the zone: x = (0.1 + 0.3/2) = 0.25 → 480 px
        #                    y = (0.2 + 0.4/2) = 0.40 → 432 px
        pixel = img.pixelColor(480, 432)
        # Translucent magenta over a transparent background should retain
        # the magenta tint (R+B > G).
        assert self._magenta_threshold(pixel), (
            f"Expected magenta-tinted pixel, got r={pixel.red()} "
            f"g={pixel.green()} b={pixel.blue()} a={pixel.alpha()}"
        )
        overlay.close()

    def test_zones_hidden_when_toggle_off(self, qapp):
        from PySide6.QtGui import QImage

        overlay = self._make_overlay(qapp)
        overlay.set_phone_zones([(0.1, 0.2, 0.3, 0.4)])
        overlay.set_phone_zones_visible(False)
        qapp.processEvents()

        img = QImage(overlay.size(), QImage.Format_ARGB32)
        img.fill(0)
        overlay.render(img)

        pixel = img.pixelColor(480, 432)
        assert not self._magenta_threshold(pixel)
        overlay.close()

    def test_click_on_zone_does_not_select_a_plate(self, qapp):
        """A left-click inside a phone zone (no plate beneath) must not
        select anything — zones are non-interactive.
        """
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        overlay = self._make_overlay(qapp)
        overlay.set_clip_data(ClipPlateData(clip_index=0))  # no plates
        overlay.set_current_frame(0, force=True)
        overlay.set_phone_zones([(0.1, 0.2, 0.3, 0.4)])
        overlay.set_phone_zones_visible(True)
        qapp.processEvents()

        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(480, 432),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        overlay.mousePressEvent(press)

        assert overlay.selected_box() is None
        assert overlay._selected_idx == -1
        overlay.close()
