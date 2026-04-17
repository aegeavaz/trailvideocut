"""Tests for exclusion-range sidecar persistence."""

from __future__ import annotations

import json
import os

import pytest

from trailvideocut.video.exclusions import (
    ExclusionRange,
    delete_exclusions,
    get_exclusions_path,
    load_exclusions,
    save_exclusions,
)


class TestGetExclusionsPath:
    def test_sidecar_filename(self, tmp_path):
        video = tmp_path / "trail.mp4"
        assert get_exclusions_path(video).name == "trail.exclusions.json"
        assert get_exclusions_path(video).parent == tmp_path


class TestRoundTrip:
    def test_save_and_load_preserves_ranges(self, tmp_path):
        video = tmp_path / "trail.mp4"
        video.touch()
        ranges = [ExclusionRange(0.0, 12.5), ExclusionRange(30.0, 45.25)]

        save_exclusions(video, ranges)
        loaded = load_exclusions(video)

        assert len(loaded) == 2
        for orig, got in zip(ranges, loaded):
            assert got.start == pytest.approx(orig.start)
            assert got.end == pytest.approx(orig.end)

    def test_save_empty_list_roundtrips(self, tmp_path):
        video = tmp_path / "trail.mp4"
        video.touch()
        save_exclusions(video, [])
        assert load_exclusions(video) == []


class TestLoadValidation:
    def test_missing_file_returns_empty(self, tmp_path):
        video = tmp_path / "nonexistent.mp4"
        assert load_exclusions(video) == []

    def test_corrupt_json_returns_empty(self, tmp_path, caplog):
        video = tmp_path / "bad.mp4"
        video.touch()
        get_exclusions_path(video).write_text("{not json", encoding="utf-8")

        with caplog.at_level("WARNING"):
            assert load_exclusions(video) == []
        assert any("Failed to read" in rec.message for rec in caplog.records)

    def test_wrong_version_returns_empty(self, tmp_path, caplog):
        video = tmp_path / "old.mp4"
        video.touch()
        get_exclusions_path(video).write_text(
            json.dumps({"version": 99, "video_filename": "old.mp4", "ranges": []}),
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            assert load_exclusions(video) == []
        assert any("unsupported version" in rec.message for rec in caplog.records)

    def test_filename_mismatch_returns_empty(self, tmp_path, caplog):
        video = tmp_path / "current.mp4"
        video.touch()
        get_exclusions_path(video).write_text(
            json.dumps({
                "version": 1,
                "video_filename": "other.mp4",
                "ranges": [{"start": 1.0, "end": 2.0}],
            }),
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            assert load_exclusions(video) == []
        assert any("references" in rec.message for rec in caplog.records)

    def test_missing_ranges_key_returns_empty(self, tmp_path):
        video = tmp_path / "v.mp4"
        video.touch()
        get_exclusions_path(video).write_text(
            json.dumps({"version": 1, "video_filename": "v.mp4"}),
            encoding="utf-8",
        )
        assert load_exclusions(video) == []

    def test_malformed_entry_skipped(self, tmp_path, caplog):
        video = tmp_path / "v.mp4"
        video.touch()
        get_exclusions_path(video).write_text(
            json.dumps({
                "version": 1,
                "video_filename": "v.mp4",
                "ranges": [
                    {"start": 1.0, "end": 2.0},
                    {"start": "not a float", "end": 5.0},
                    {"start": 10.0, "end": 8.0},
                    {"start": 20.0, "end": 30.0},
                ],
            }),
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            loaded = load_exclusions(video)
        assert len(loaded) == 2
        assert loaded[0].start == 1.0
        assert loaded[1].start == 20.0


class TestWritePermissionDenied:
    def test_readonly_dir_logs_warning(self, tmp_path, caplog):
        if os.geteuid() == 0:
            pytest.skip("Root bypasses filesystem permissions")

        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        video = ro_dir / "trail.mp4"
        video.touch()
        ro_dir.chmod(0o500)
        try:
            with caplog.at_level("WARNING"):
                save_exclusions(video, [ExclusionRange(0, 5)])
            assert any("Cannot save exclusions" in rec.message for rec in caplog.records)
        finally:
            ro_dir.chmod(0o700)


class TestDelete:
    def test_delete_removes_sidecar(self, tmp_path):
        video = tmp_path / "trail.mp4"
        video.touch()
        save_exclusions(video, [ExclusionRange(0, 5)])
        assert get_exclusions_path(video).exists()

        delete_exclusions(video)
        assert not get_exclusions_path(video).exists()

    def test_delete_nonexistent_no_error(self, tmp_path):
        delete_exclusions(tmp_path / "nope.mp4")
