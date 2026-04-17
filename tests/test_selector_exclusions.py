"""Tests for exclusion-range integration in SegmentSelector."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from trailvideocut.audio.models import AudioAnalysis, BeatInfo, MusicSection
from trailvideocut.config import TrailVideoCutConfig
from trailvideocut.editor.selector import SegmentSelector
from trailvideocut.video.models import InterestScore, VideoSegment


def _make_config(excluded_ranges=None) -> TrailVideoCutConfig:
    return TrailVideoCutConfig(
        video_path=Path("test.mp4"),
        audio_path=Path("test.wav"),
        excluded_ranges=excluded_ranges or [],
    )


def _make_segments(n: int, hop: float = 0.5, window: float = 2.0) -> list[VideoSegment]:
    rng = random.Random(42)
    segs = []
    for i in range(n):
        t = i * hop
        segs.append(
            VideoSegment(
                start_time=t,
                end_time=t + window,
                interest=InterestScore(
                    optical_flow=rng.random(),
                    color_change=rng.random(),
                    edge_variance=rng.random(),
                    brightness_change=rng.random(),
                ),
            )
        )
    return segs


def _make_audio(n_beats: int = 10, interval: float = 0.5) -> AudioAnalysis:
    beats = [
        BeatInfo(
            timestamp=i * interval,
            strength=0.8 if i % 4 == 0 else 0.5,
            is_downbeat=i % 4 == 0,
        )
        for i in range(n_beats)
    ]
    return AudioAnalysis(
        duration=beats[-1].timestamp,
        tempo=120.0,
        beats=beats,
        sections=[
            MusicSection(
                label="section",
                start_time=beats[0].timestamp,
                end_time=beats[-1].timestamp,
                energy=0.5,
            )
        ],
    )


class TestBaselineBehaviour:
    def test_empty_exclusions_matches_no_config(self):
        """Baseline: empty excluded_ranges → identical CutPlan to no-exclusion config."""
        audio = _make_audio(10, 0.5)
        segments = _make_segments(40)

        plan_a = SegmentSelector(_make_config()).select(audio, segments)
        plan_b = SegmentSelector(
            _make_config(excluded_ranges=[])
        ).select(audio, segments)

        assert len(plan_a.decisions) == len(plan_b.decisions)
        for a, b in zip(plan_a.decisions, plan_b.decisions):
            assert a.source_start == pytest.approx(b.source_start)
            assert a.source_end == pytest.approx(b.source_end)
            assert a.target_start == pytest.approx(b.target_start)
            assert a.target_end == pytest.approx(b.target_end)


class TestExclusionFilter:
    def test_midpoint_inside_excluded_segment_dropped(self):
        """Segments whose midpoint sits inside an exclusion are removed."""
        audio = _make_audio(10, 0.5)
        segments = _make_segments(40)

        excluded_zone = (5.0, 10.0)
        plan = SegmentSelector(
            _make_config(excluded_ranges=[excluded_zone])
        ).select(audio, segments)

        for d in plan.decisions:
            source_mid = (d.source_start + d.source_end) / 2
            assert not (
                excluded_zone[0] < source_mid < excluded_zone[1]
            ), f"Clip midpoint {source_mid} falls inside exclusion {excluded_zone}"

    def test_midpoint_on_boundary_retained(self):
        """A segment whose midpoint equals an exclusion endpoint is NOT filtered."""
        selector = SegmentSelector(_make_config(excluded_ranges=[(0.0, 5.0)]))

        seg_on_boundary = VideoSegment(
            start_time=4.0,
            end_time=6.0,
            interest=InterestScore(0.5, 0.5, 0.5, 0.5),
        )
        seg_inside = VideoSegment(
            start_time=2.0,
            end_time=4.0,
            interest=InterestScore(0.5, 0.5, 0.5, 0.5),
        )

        kept = selector._filter_excluded([seg_on_boundary, seg_inside])

        assert seg_on_boundary in kept
        assert seg_inside not in kept


class TestUndercountAndEmptyPaths:
    def test_undercount_emits_warning_with_excluded_duration(self, caplog):
        """When exclusion cuts the pool below target, warn with counts + excluded duration."""
        audio = _make_audio(20, 0.5)  # 19 beat intervals requested
        segments = _make_segments(40, hop=0.5, window=2.0)

        # Remove midpoints in (0.5, 18.5) — only a handful of segments survive
        # at the edges, so even the no-constraint fallback can't reach 19.
        excluded = [(0.5, 18.5)]

        with caplog.at_level("WARNING"):
            SegmentSelector(
                _make_config(excluded_ranges=excluded)
            ).select(audio, segments)

        msgs = [rec.message for rec in caplog.records]
        assert any("excluded" in m.lower() and "range" in m.lower() for m in msgs), (
            f"Expected a warning mentioning exclusion ranges, got: {msgs}"
        )

    def test_empty_after_exclusion_raises(self):
        """Exclusions that wipe out every candidate raise RuntimeError citing exclusions."""
        audio = _make_audio(10, 0.5)
        segments = _make_segments(40)
        # Full video duration covered by exclusion.
        excluded = [(0.0, 100.0)]

        with pytest.raises(RuntimeError, match="exclusion"):
            SegmentSelector(
                _make_config(excluded_ranges=excluded)
            ).select(audio, segments)
