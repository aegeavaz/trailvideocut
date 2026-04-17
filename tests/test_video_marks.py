"""Tests for must-include-marks sidecar persistence."""

from __future__ import annotations

import json
import os

import pytest

from trailvideocut.video.marks import (
    delete_marks,
    get_marks_path,
    load_marks,
    save_marks,
)


class TestGetMarksPath:
    def test_sidecar_filename(self, tmp_path):
        video = tmp_path / "ride.mp4"
        assert get_marks_path(video).name == "ride.marks.json"
        assert get_marks_path(video).parent == tmp_path

    def test_sidecar_filename_no_extension(self, tmp_path):
        video = tmp_path / "ride"
        assert get_marks_path(video).name == "ride.marks.json"


class TestRoundTrip:
    def test_save_and_load_preserves_marks(self, tmp_path):
        video = tmp_path / "ride.mp4"
        video.touch()
        marks = [3.5, 1.25, 42.0]

        save_marks(video, marks)
        loaded = load_marks(video)

        assert loaded == [1.25, 3.5, 42.0]

    def test_save_empty_list_writes_empty_array(self, tmp_path):
        video = tmp_path / "ride.mp4"
        video.touch()
        save_marks(video, [])

        sidecar = get_marks_path(video)
        assert sidecar.exists()
        payload = json.loads(sidecar.read_text())
        assert payload["marks"] == []
        assert payload["version"] == 1
        assert payload["video_filename"] == "ride.mp4"

    def test_save_writes_versioned_schema(self, tmp_path):
        video = tmp_path / "ride.mp4"
        video.touch()
        save_marks(video, [2.0, 1.0])

        payload = json.loads(get_marks_path(video).read_text())
        assert payload["version"] == 1
        assert payload["video_filename"] == "ride.mp4"
        assert payload["marks"] == [1.0, 2.0]


class TestLoadValidation:
    def test_missing_file_returns_empty_silently(self, tmp_path, caplog):
        video = tmp_path / "nope.mp4"
        with caplog.at_level("WARNING"):
            assert load_marks(video) == []
        assert caplog.records == []

    def test_corrupt_json_returns_empty(self, tmp_path, caplog):
        video = tmp_path / "bad.mp4"
        video.touch()
        get_marks_path(video).write_text("{not json", encoding="utf-8")

        with caplog.at_level("WARNING"):
            assert load_marks(video) == []
        assert any("Failed to read" in rec.message for rec in caplog.records)

    def test_wrong_version_returns_empty(self, tmp_path, caplog):
        video = tmp_path / "old.mp4"
        video.touch()
        get_marks_path(video).write_text(
            json.dumps({"version": 99, "video_filename": "old.mp4", "marks": []}),
            encoding="utf-8",
        )

        with caplog.at_level("WARNING"):
            assert load_marks(video) == []
        assert any("unsupported version" in rec.message for rec in caplog.records)

    def test_filename_mismatch_returns_empty(self, tmp_path, caplog):
        video = tmp_path / "current.mp4"
        video.touch()
        get_marks_path(video).write_text(
            json.dumps({
                "version": 1,
                "video_filename": "other.mp4",
                "marks": [1.0, 2.0],
            }),
            encoding="utf-8",
        )

        with caplog.at_level("WARNING"):
            assert load_marks(video) == []
        assert any("references" in rec.message for rec in caplog.records)

    def test_missing_marks_key_returns_empty(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.touch()
        get_marks_path(video).write_text(
            json.dumps({"version": 1, "video_filename": "v.mp4"}),
            encoding="utf-8",
        )
        assert load_marks(video) == []

    def test_top_level_not_object_or_array(self, tmp_path, caplog):
        video = tmp_path / "v.mp4"
        video.touch()
        get_marks_path(video).write_text(
            json.dumps("just a string"),
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            assert load_marks(video) == []


class TestLegacyFormat:
    def test_bare_array_loaded_sorted(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.touch()
        get_marks_path(video).write_text(
            json.dumps([3.4, 1.2, 5.6]),
            encoding="utf-8",
        )
        assert load_marks(video) == [1.2, 3.4, 5.6]

    def test_bare_array_with_non_numeric_entry_rejected(self, tmp_path, caplog):
        video = tmp_path / "v.mp4"
        video.touch()
        get_marks_path(video).write_text(
            json.dumps([1.2, "oops", 5.6]),
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            assert load_marks(video) == []
        assert any("malformed" in rec.message.lower() for rec in caplog.records)

    def test_bare_empty_array_loads_empty(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.touch()
        get_marks_path(video).write_text("[]", encoding="utf-8")
        assert load_marks(video) == []

    def test_legacy_upgraded_on_next_save(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.touch()
        get_marks_path(video).write_text(
            json.dumps([1.0, 2.0]),
            encoding="utf-8",
        )
        loaded = load_marks(video)
        assert loaded == [1.0, 2.0]

        save_marks(video, loaded + [3.0])
        payload = json.loads(get_marks_path(video).read_text())
        assert isinstance(payload, dict)
        assert payload["version"] == 1
        assert payload["marks"] == [1.0, 2.0, 3.0]


class TestDelete:
    def test_delete_removes_sidecar(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.touch()
        save_marks(video, [1.0])
        assert get_marks_path(video).exists()

        delete_marks(video)
        assert not get_marks_path(video).exists()

    def test_delete_nonexistent_no_error(self, tmp_path, caplog):
        with caplog.at_level("WARNING"):
            delete_marks(tmp_path / "nope.mp4")
        assert caplog.records == []


class TestWritePermissionDenied:
    def test_readonly_dir_logs_warning_and_does_not_raise(self, tmp_path, caplog):
        if os.name == "nt":
            pytest.skip("POSIX-only permission test")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("Root bypasses filesystem permissions")

        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        video = ro_dir / "v.mp4"
        video.touch()
        ro_dir.chmod(0o500)
        try:
            with caplog.at_level("WARNING"):
                save_marks(video, [1.0])
            assert any("Cannot save marks" in rec.message for rec in caplog.records)
        finally:
            ro_dir.chmod(0o700)
