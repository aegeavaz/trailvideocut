"""Widget tests for ExclusionsTab and scrubber overlay."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.ui.exclusions_tab import ExclusionsTab
from trailvideocut.ui.video_player import ClickSlider


class TestExclusionsTab:
    def test_start_end_adds_range(self, qapp):
        tab = ExclusionsTab()
        emitted: list = []
        tab.ranges_changed.connect(emitted.append)

        tab.set_player_position(2.0)
        tab.capture_start()
        tab.set_player_position(6.0)
        tab.capture_end()

        assert tab.ranges == [(2.0, 6.0)]
        assert emitted == [[(2.0, 6.0)]]

    def test_end_before_start_rejected_without_exception(self, qapp):
        tab = ExclusionsTab()
        emitted: list = []
        tab.ranges_changed.connect(emitted.append)

        tab.set_player_position(5.0)
        tab.capture_start()
        tab.set_player_position(3.0)
        tab.capture_end()

        assert tab.ranges == []
        assert emitted == []

    def test_cancel_pending_start(self, qapp):
        tab = ExclusionsTab()
        tab.set_player_position(3.0)
        tab.capture_start()
        tab.cancel_pending()
        tab.set_player_position(5.0)
        tab.capture_end()
        # End without Start is a no-op
        assert tab.ranges == []

    def test_set_ranges_sorts_and_suppresses_signal(self, qapp):
        tab = ExclusionsTab()
        emitted: list = []
        tab.ranges_changed.connect(emitted.append)

        tab.set_ranges([(30.0, 45.0), (0.0, 5.0)])
        assert tab.ranges == [(0.0, 5.0), (30.0, 45.0)]
        # set_ranges is for load-side use and must NOT emit ranges_changed
        assert emitted == []

    def test_multiple_ranges_sorted_on_insert(self, qapp):
        tab = ExclusionsTab()
        tab.set_player_position(40.0)
        tab.capture_start()
        tab.set_player_position(50.0)
        tab.capture_end()
        tab.set_player_position(10.0)
        tab.capture_start()
        tab.set_player_position(20.0)
        tab.capture_end()

        assert tab.ranges == [(10.0, 20.0), (40.0, 50.0)]


class TestClickSliderExcludedSpans:
    def test_stores_normalized_spans(self, qapp):
        from PySide6.QtCore import Qt

        slider = ClickSlider(Qt.Horizontal)
        slider.set_excluded_spans([(0.0, 50.0), (75.0, 100.0)], duration=100.0)
        assert slider._excluded_spans == [(0.0, 0.5), (0.75, 1.0)]

    def test_zero_duration_empties_list(self, qapp):
        from PySide6.QtCore import Qt

        slider = ClickSlider(Qt.Horizontal)
        slider.set_excluded_spans([(0.0, 5.0)], duration=0.0)
        assert slider._excluded_spans == []

    def test_out_of_bounds_clipped(self, qapp):
        from PySide6.QtCore import Qt

        slider = ClickSlider(Qt.Horizontal)
        slider.set_excluded_spans([(-5.0, 150.0)], duration=100.0)
        assert slider._excluded_spans == [(0.0, 1.0)]

    def test_multiple_ranges_paintable(self, qapp):
        """Smoke test: painting the slider with 0/1/many ranges does not crash."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        slider = ClickSlider(Qt.Horizontal)
        slider.resize(200, 40)

        for ranges in ([], [(0, 10)], [(0, 10), (30, 50)]):
            slider.set_excluded_spans(ranges, duration=100.0)
            img = QImage(200, 40, QImage.Format_ARGB32)
            slider.render(img)  # must not raise
