"""Pipeline-level validation tests for excluded ranges."""

from __future__ import annotations

from pathlib import Path

import pytest

from trailvideocut.config import TrailVideoCutConfig
from trailvideocut.pipeline import TrailVideoCutPipeline


@pytest.fixture
def fake_video(tmp_path, monkeypatch):
    """Create placeholder video/audio files and stub duration probe."""
    video = tmp_path / "clip.mp4"
    video.touch()
    audio = tmp_path / "song.mp3"
    audio.touch()

    # Probe returns 60s so ranges can be bounds-checked without a real file.
    monkeypatch.setattr(
        TrailVideoCutPipeline,
        "_probe_video_duration",
        lambda self: 60.0,
    )
    return video, audio


def _make_pipeline(video: Path, audio: Path, **config_kwargs) -> TrailVideoCutPipeline:
    config = TrailVideoCutConfig(video_path=video, audio_path=audio, **config_kwargs)
    return TrailVideoCutPipeline(config)


class TestValidateInputsExclusions:
    def test_valid_exclusions_accepted(self, fake_video):
        video, audio = fake_video
        pipe = _make_pipeline(
            video, audio,
            excluded_ranges=[(0.0, 10.0), (30.0, 40.0)],
        )
        pipe._validate_inputs()

    def test_inverted_range_rejected(self, fake_video):
        video, audio = fake_video
        with pytest.raises(ValueError, match="start < end"):
            _make_pipeline(
                video, audio,
                excluded_ranges=[(30.0, 10.0)],
            )._validate_inputs()

    def test_out_of_duration_rejected(self, fake_video):
        video, audio = fake_video
        pipe = _make_pipeline(
            video, audio,
            excluded_ranges=[(0.0, 120.0)],
        )
        with pytest.raises(ValueError, match="outside video duration"):
            pipe._validate_inputs()

    def test_overlapping_ranges_rejected(self, fake_video):
        video, audio = fake_video
        pipe = _make_pipeline(
            video, audio,
            excluded_ranges=[(0.0, 20.0), (10.0, 30.0)],
        )
        with pytest.raises(ValueError, match="overlap"):
            pipe._validate_inputs()

    def test_include_collision_rejected(self, fake_video):
        video, audio = fake_video
        pipe = _make_pipeline(
            video, audio,
            excluded_ranges=[(10.0, 20.0)],
            include_timestamps=[15.0],
        )
        with pytest.raises(ValueError, match="15"):
            pipe._validate_inputs()

    def test_empty_exclusions_skip_probe(self, tmp_path, monkeypatch):
        video = tmp_path / "c.mp4"
        video.touch()
        audio = tmp_path / "s.mp3"
        audio.touch()

        called = {"n": 0}

        def probe(self):
            called["n"] += 1
            return 60.0

        monkeypatch.setattr(TrailVideoCutPipeline, "_probe_video_duration", probe)
        _make_pipeline(video, audio)._validate_inputs()
        assert called["n"] == 0
