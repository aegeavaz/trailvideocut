"""Tests for the Review-page "Plate Model" combo-box (§5 of the
`plate-detector-larger-model` change).

Covers:
- Combo defaults to variant `"n"` on construction.
- Changing the combo updates `_current_plate_variant()`.
- The download worker is constructed with the selected variant.
- The selection does not persist across ReviewPage instances (no `QSettings`).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.ui.review_page import ReviewPage


@pytest.fixture
def review_page(qapp):
    page = ReviewPage()
    yield page
    page.close()


class TestPlateModelCombo:
    def test_default_selection_is_m(self, review_page):
        assert review_page._combo_plate_model.currentData() == "m"
        assert review_page._current_plate_variant() == "m"

    def test_combo_items_cover_n_s_m(self, review_page):
        combo = review_page._combo_plate_model
        assert combo.count() == 3
        assert {combo.itemData(i) for i in range(combo.count())} == {"n", "s", "m"}

    def test_changing_selection_updates_variant(self, review_page):
        combo = review_page._combo_plate_model
        for idx in range(combo.count()):
            expected = combo.itemData(idx)
            combo.setCurrentIndex(idx)
            assert review_page._current_plate_variant() == expected

    def test_no_persistence_across_instances(self, qapp):
        """A fresh ReviewPage resets to the default variant ("m") regardless
        of the prior page's selection.

        Guards the §5.4 invariant that the combo does not route through
        `QSettings` or any other persistence layer.
        """
        first = ReviewPage()
        try:
            # Pretend the user previously chose "n" (non-default).
            idx_n = next(
                i for i in range(first._combo_plate_model.count())
                if first._combo_plate_model.itemData(i) == "n"
            )
            first._combo_plate_model.setCurrentIndex(idx_n)
            assert first._current_plate_variant() == "n"
        finally:
            first.close()

        second = ReviewPage()
        try:
            assert second._current_plate_variant() == "m"
        finally:
            second.close()


class TestDownloadWorkerReceivesSelectedVariant:
    """§5.3 — clicking "Detect Plates" constructs the download worker with
    the currently-selected variant (verified via `_start_model_download`,
    the code path both detect-frame and detect-plates funnel through when
    the cache is empty).
    """

    def _set_variant(self, page, variant: str) -> None:
        combo = page._combo_plate_model
        idx = next(
            i for i in range(combo.count())
            if combo.itemData(i) == variant
        )
        combo.setCurrentIndex(idx)

    def test_worker_receives_default_variant_m(self, review_page):
        """Default combo selection → worker built with "m"."""
        captured: dict[str, object] = {}

        class _RecordingWorker:
            def __init__(self, parent=None, variant="m"):
                captured["variant"] = variant
                self.progress = _Signal()
                self.finished = _Signal()
                self.error = _Signal()

            def start(self):
                captured["started"] = True

            def terminate(self):
                pass

        with patch(
            "trailvideocut.ui.workers.ModelDownloadWorker", _RecordingWorker,
        ):
            review_page._start_model_download()
        assert captured["variant"] == "m"
        assert captured.get("started") is True

    def test_worker_receives_variant_n_when_selected(self, review_page):
        self._set_variant(review_page, "n")
        captured: dict[str, object] = {}

        class _RecordingWorker:
            def __init__(self, parent=None, variant="m"):
                captured["variant"] = variant
                self.progress = _Signal()
                self.finished = _Signal()
                self.error = _Signal()

            def start(self):
                pass

            def terminate(self):
                pass

        with patch(
            "trailvideocut.ui.workers.ModelDownloadWorker", _RecordingWorker,
        ):
            review_page._start_model_download()
        assert captured["variant"] == "n"

    def test_worker_receives_variant_s_when_selected(self, review_page):
        self._set_variant(review_page, "s")
        captured: dict[str, object] = {}

        class _RecordingWorker:
            def __init__(self, parent=None, variant="m"):
                captured["variant"] = variant
                self.progress = _Signal()
                self.finished = _Signal()
                self.error = _Signal()

            def start(self):
                pass

            def terminate(self):
                pass

        with patch(
            "trailvideocut.ui.workers.ModelDownloadWorker", _RecordingWorker,
        ):
            review_page._start_model_download()
        assert captured["variant"] == "s"


class _Signal:
    """Minimal replacement for Qt `Signal` to satisfy `connect(...)` calls."""

    def connect(self, _slot):
        return None

    def emit(self, *_args, **_kwargs):
        return None
