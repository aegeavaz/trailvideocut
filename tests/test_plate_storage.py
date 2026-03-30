"""Tests for plate data persistence (storage module)."""

import json
from pathlib import Path

import pytest

from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.plate.storage import (
    delete_plates,
    get_plates_path,
    load_plates,
    save_plates,
)


@pytest.fixture
def sample_plate_data():
    """Create sample plate data with two clips."""
    box1 = PlateBox(x=0.1, y=0.2, w=0.05, h=0.03, confidence=0.92, manual=False)
    box2 = PlateBox(x=0.5, y=0.6, w=0.08, h=0.04, confidence=0.0, manual=True)
    return {
        0: ClipPlateData(clip_index=0, detections={42: [box1], 43: [box1, box2]}),
        2: ClipPlateData(clip_index=2, detections={100: [box2]}),
    }


class TestGetPlatesPath:
    def test_produces_correct_sidecar_filename(self):
        assert get_plates_path("/videos/trail.mp4") == Path("/videos/trail.plates.json")

    def test_handles_multiple_dots_in_name(self):
        assert get_plates_path("/a/b/my.video.avi") == Path("/a/b/my.video.plates.json")

    def test_accepts_path_object(self):
        assert get_plates_path(Path("/v/clip.mov")) == Path("/v/clip.plates.json")


class TestRoundTrip:
    def test_save_then_load_produces_identical_data(self, tmp_path, sample_plate_data):
        video = tmp_path / "trail.mp4"
        video.touch()

        save_plates(video, sample_plate_data)
        loaded = load_plates(video)

        assert set(loaded.keys()) == set(sample_plate_data.keys())
        for clip_idx in sample_plate_data:
            orig = sample_plate_data[clip_idx]
            got = loaded[clip_idx]
            assert got.clip_index == orig.clip_index
            assert set(got.detections.keys()) == set(orig.detections.keys())
            for frame in orig.detections:
                assert len(got.detections[frame]) == len(orig.detections[frame])
                for ob, gb in zip(orig.detections[frame], got.detections[frame]):
                    assert gb.x == pytest.approx(ob.x)
                    assert gb.y == pytest.approx(ob.y)
                    assert gb.w == pytest.approx(ob.w)
                    assert gb.h == pytest.approx(ob.h)
                    assert gb.confidence == pytest.approx(ob.confidence)
                    assert gb.manual == ob.manual


class TestLoadValidation:
    def test_missing_file_returns_empty(self, tmp_path):
        video = tmp_path / "nonexistent.mp4"
        assert load_plates(video) == {}

    def test_corrupt_json_returns_empty(self, tmp_path):
        video = tmp_path / "bad.mp4"
        video.touch()
        sidecar = tmp_path / "bad.plates.json"
        sidecar.write_text("not valid json {{{", encoding="utf-8")
        assert load_plates(video) == {}

    def test_wrong_version_returns_empty(self, tmp_path):
        video = tmp_path / "old.mp4"
        video.touch()
        sidecar = tmp_path / "old.plates.json"
        sidecar.write_text(json.dumps({"version": 999, "clips": {}}), encoding="utf-8")
        assert load_plates(video) == {}

    def test_mismatched_clip_indices_discarded(self, tmp_path, sample_plate_data):
        video = tmp_path / "trail.mp4"
        video.touch()
        save_plates(video, sample_plate_data)

        # Only clip 0 is valid
        loaded = load_plates(video, valid_clip_indices={0})
        assert 0 in loaded
        assert 2 not in loaded


class TestDeletePlates:
    def test_delete_removes_sidecar(self, tmp_path, sample_plate_data):
        video = tmp_path / "trail.mp4"
        video.touch()
        save_plates(video, sample_plate_data)
        sidecar = get_plates_path(video)
        assert sidecar.exists()

        delete_plates(video)
        assert not sidecar.exists()

    def test_delete_nonexistent_no_error(self, tmp_path):
        video = tmp_path / "nope.mp4"
        delete_plates(video)  # should not raise
