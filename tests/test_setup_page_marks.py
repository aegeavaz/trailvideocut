"""Widget tests for SetupPage marks auto-persistence."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.ui.setup_page import SetupPage
from trailvideocut.video.marks import get_marks_path


@pytest.fixture
def page(qapp):
    """A fresh SetupPage; parent=None keeps it detached from a main window."""
    p = SetupPage()
    yield p
    p.deleteLater()


def _make_video(tmp_path, name="ride.mp4"):
    video = tmp_path / name
    video.touch()
    return video


class TestMarksTabButtons:
    def test_save_and_load_buttons_absent(self, page):
        """Marks tab exposes only Add / Remove / Clear controls (no Save/Load)."""
        from PySide6.QtWidgets import QPushButton

        button_texts = [
            b.text() for b in page.findChildren(QPushButton)
            if b.text() and "mark" in b.text().lower()
        ]
        # Expect at least the Add control; explicitly no Save/Load
        assert any("Add Mark" in t for t in button_texts)
        assert not any("Save Marks" in t for t in button_texts)
        assert not any("Load Marks" in t for t in button_texts)


class TestAutoLoadOnOpen:
    def test_existing_sidecar_populates_marks(self, page, tmp_path):
        video = _make_video(tmp_path)
        get_marks_path(video).write_text(
            json.dumps({
                "version": 1,
                "video_filename": video.name,
                "marks": [1.5, 4.25, 7.0],
            }),
            encoding="utf-8",
        )
        page._video_path.setText(str(video))

        page._auto_load_marks(video)

        assert page._marks == [1.5, 4.25, 7.0]
        assert page._selected_mark_index == -1
        assert not page._btn_remove_mark.isEnabled()

    def test_no_sidecar_leaves_marks_empty(self, page, tmp_path):
        video = _make_video(tmp_path)
        page._video_path.setText(str(video))

        page._auto_load_marks(video)

        assert page._marks == []


class TestAutoSaveOnMutation:
    def _stub_current_time(self, page, monkeypatch, t: float):
        """Patch the player's `current_time` property to a fixed value."""
        from trailvideocut.ui.video_player import VideoPlayer
        monkeypatch.setattr(VideoPlayer, "current_time", property(lambda _self: t))

    def test_add_mark_writes_sidecar(self, page, tmp_path, monkeypatch):
        video = _make_video(tmp_path)
        page._video_path.setText(str(video))
        self._stub_current_time(page, monkeypatch, 12.5)

        page._add_mark()

        assert page._marks == [12.5]
        payload = json.loads(get_marks_path(video).read_text())
        assert payload["version"] == 1
        assert payload["video_filename"] == video.name
        assert payload["marks"] == [12.5]

    def test_remove_nearest_mark_when_nothing_selected(self, page, tmp_path, monkeypatch):
        """`D` with no chip selected removes the mark nearest the player time."""
        video = _make_video(tmp_path)
        page._video_path.setText(str(video))
        get_marks_path(video).write_text(
            json.dumps({
                "version": 1,
                "video_filename": video.name,
                "marks": [1.0, 5.0, 9.0],
            }),
            encoding="utf-8",
        )
        page._auto_load_marks(video)
        assert page._selected_mark_index == -1

        # Player is near the middle mark — pressing D should drop that one.
        self._stub_current_time(page, monkeypatch, 4.7)
        page._remove_mark()

        assert page._marks == [1.0, 9.0]
        assert json.loads(get_marks_path(video).read_text())["marks"] == [1.0, 9.0]

    def test_remove_with_empty_list_is_no_op(self, page, tmp_path, monkeypatch):
        video = _make_video(tmp_path)
        page._video_path.setText(str(video))
        self._stub_current_time(page, monkeypatch, 2.0)

        page._remove_mark()  # must not raise / must not create a sidecar

        assert page._marks == []
        assert not get_marks_path(video).exists()

    def test_remove_selected_mark_writes_sidecar(self, page, tmp_path, monkeypatch):
        video = _make_video(tmp_path)
        page._video_path.setText(str(video))

        # Seed two marks via auto-load so we bypass player time-stubbing
        get_marks_path(video).write_text(
            json.dumps({
                "version": 1,
                "video_filename": video.name,
                "marks": [3.0, 8.0],
            }),
            encoding="utf-8",
        )
        page._auto_load_marks(video)
        assert page._marks == [3.0, 8.0]

        # Select the first mark, then remove it.
        page._selected_mark_index = 0
        page._btn_remove_mark.setEnabled(True)
        page._remove_mark()

        assert page._marks == [8.0]
        payload = json.loads(get_marks_path(video).read_text())
        assert payload["marks"] == [8.0]

    def test_clear_all_writes_empty_array_sidecar(self, page, tmp_path):
        video = _make_video(tmp_path)
        page._video_path.setText(str(video))

        get_marks_path(video).write_text(
            json.dumps({
                "version": 1,
                "video_filename": video.name,
                "marks": [1.0, 2.0, 3.0],
            }),
            encoding="utf-8",
        )
        page._auto_load_marks(video)

        page._clear_marks()

        assert page._marks == []
        payload = json.loads(get_marks_path(video).read_text())
        assert payload["marks"] == []
        assert payload["version"] == 1

    def test_mutations_without_video_path_are_no_op_on_disk(self, page, tmp_path, monkeypatch):
        """No video selected → auto-save silently skips; no crash."""
        self._stub_current_time(page, monkeypatch, 5.0)
        assert page._video_path.text().strip() == ""

        page._add_mark()  # should not raise

        assert page._marks == [5.0]
        # No sidecar file should exist anywhere under tmp_path
        assert list(tmp_path.glob("*.marks.json")) == []


class TestScrubberMarkRace:
    """Marks set before the async video load reports duration must still paint."""

    def test_marks_repainted_when_duration_arrives(self, page, tmp_path):
        video = _make_video(tmp_path)
        get_marks_path(video).write_text(
            json.dumps({
                "version": 1,
                "video_filename": video.name,
                "marks": [1.0, 2.5, 4.0],
            }),
            encoding="utf-8",
        )
        page._video_path.setText(str(video))

        # Simulate the real-world ordering: marks arrive before the media
        # player has resolved duration (QMediaPlayer is async).
        page._auto_load_marks(video)
        slider = page._player._slider
        assert slider._marks == []  # duration still 0 → nothing to paint yet

        # Duration arrives: slider must now carry the normalized mark positions.
        page._player._on_duration_changed(10_000)
        assert slider._marks == [0.1, 0.25, 0.4]
