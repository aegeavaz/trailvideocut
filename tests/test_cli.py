"""CLI tests — focused on the new exclusion flag parsing."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from trailvideocut.cli import _parse_exclusion, app


class TestParseExclusion:
    def test_valid(self):
        assert _parse_exclusion("0:30") == (0.0, 30.0)

    def test_valid_with_decimals(self):
        assert _parse_exclusion("1.5:4.25") == (1.5, 4.25)

    def test_missing_colon(self):
        with pytest.raises(typer.BadParameter, match="START:END"):
            _parse_exclusion("30")

    def test_too_many_colons(self):
        with pytest.raises(typer.BadParameter, match="START:END"):
            _parse_exclusion("1:2:3")

    def test_non_numeric(self):
        with pytest.raises(typer.BadParameter, match="numeric"):
            _parse_exclusion("abc:10")

    def test_negative(self):
        with pytest.raises(typer.BadParameter, match="non-negative"):
            _parse_exclusion("5:-1")

    def test_inverted(self):
        with pytest.raises(typer.BadParameter, match="start < end"):
            _parse_exclusion("30:10")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_files(tmp_path):
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.mp3"
    video.touch()
    audio.touch()
    return video, audio


class TestCutCommandExclusionOptions:
    """Full invocations, with the pipeline stubbed, to observe config wiring and exit codes."""

    def test_single_exclude_populates_config(self, runner, sample_files, tmp_path):
        video, audio = sample_files
        captured = {}

        class FakePipeline:
            def __init__(self, config):
                captured["config"] = config
            def run(self):
                pass

        with patch("trailvideocut.cli.TrailVideoCutPipeline", FakePipeline):
            result = runner.invoke(
                app,
                ["cut", str(video), str(audio),
                 "-o", str(tmp_path / "out.mp4"),
                 "-x", "0:30", "--no-gpu"],
            )
        assert result.exit_code == 0, result.output
        assert captured["config"].excluded_ranges == [(0.0, 30.0)]

    def test_multiple_exclude_sorted(self, runner, sample_files, tmp_path):
        video, audio = sample_files
        captured = {}

        class FakePipeline:
            def __init__(self, config):
                captured["config"] = config
            def run(self):
                pass

        with patch("trailvideocut.cli.TrailVideoCutPipeline", FakePipeline):
            result = runner.invoke(
                app,
                ["cut", str(video), str(audio),
                 "-o", str(tmp_path / "out.mp4"),
                 "-x", "120.5:145", "-x", "0:30", "--no-gpu"],
            )
        assert result.exit_code == 0, result.output
        assert captured["config"].excluded_ranges == [(0.0, 30.0), (120.5, 145.0)]

    @pytest.mark.parametrize("bad_value", ["30", "abc:10", "1:2:3"])
    def test_malformed_value_errors(self, runner, sample_files, bad_value, tmp_path):
        video, audio = sample_files
        result = runner.invoke(
            app,
            ["cut", str(video), str(audio),
             "-o", str(tmp_path / "out.mp4"),
             "-x", bad_value, "--no-gpu"],
        )
        assert result.exit_code != 0
        assert bad_value in (result.output or "")

    def test_negative_value_errors(self, runner, sample_files, tmp_path):
        video, audio = sample_files
        result = runner.invoke(
            app,
            ["cut", str(video), str(audio),
             "-o", str(tmp_path / "out.mp4"),
             "-x", "5:-1", "--no-gpu"],
        )
        assert result.exit_code != 0
        assert "non-negative" in (result.output or "")

    def test_inverted_value_errors(self, runner, sample_files, tmp_path):
        video, audio = sample_files
        result = runner.invoke(
            app,
            ["cut", str(video), str(audio),
             "-o", str(tmp_path / "out.mp4"),
             "-x", "30:10", "--no-gpu"],
        )
        assert result.exit_code != 0
        assert "start < end" in (result.output or "")
