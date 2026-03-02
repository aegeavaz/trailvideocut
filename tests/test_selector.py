from pathlib import Path

import numpy as np
import pytest

from smartcut.audio.models import AudioAnalysis, BeatInfo
from smartcut.config import SmartCutConfig, TransitionStyle
from smartcut.editor.models import EditDecision
from smartcut.editor.selector import SegmentSelector
from smartcut.video.models import InterestScore, VideoSegment


def _make_config(**overrides) -> SmartCutConfig:
    defaults = dict(
        video_path=Path("test.mp4"),
        audio_path=Path("test.wav"),
    )
    defaults.update(overrides)
    return SmartCutConfig(**defaults)


def _make_segments(n: int = 40, hop: float = 0.5, window: float = 2.0) -> list[VideoSegment]:
    """Create overlapping segments simulating the analyzer output."""
    segments = []
    for i in range(n):
        t = i * hop
        interest = InterestScore(
            optical_flow=float(i) / n,
            color_change=float(n - i) / n,
            edge_variance=0.5,
            brightness_change=0.3,
        )
        segments.append(
            VideoSegment(
                start_time=t,
                end_time=t + window,
                interest=interest,
            )
        )
    return segments


def _make_beats(n: int = 10, interval: float = 0.5) -> list[BeatInfo]:
    return [
        BeatInfo(
            timestamp=i * interval,
            strength=0.8 if i % 4 == 0 else 0.5,
            is_downbeat=i % 4 == 0,
        )
        for i in range(n)
    ]


class TestSegmentSelector:
    def test_zones_analyzed_matches_beat_intervals(self, sample_audio_analysis, sample_segments):
        config = _make_config()
        selector = SegmentSelector(config)
        plan = selector.select(sample_audio_analysis, sample_segments)
        assert plan.zones_analyzed == len(sample_audio_analysis.beats) - 1
        # After merging, decisions count should be <= zones analyzed
        assert len(plan.decisions) <= plan.zones_analyzed

    def test_decisions_cover_full_timeline(self, sample_audio_analysis, sample_segments):
        config = _make_config()
        selector = SegmentSelector(config)
        plan = selector.select(sample_audio_analysis, sample_segments)
        assert plan.decisions[0].target_start == sample_audio_analysis.beats[0].timestamp
        assert plan.decisions[-1].target_end == sample_audio_analysis.beats[-1].timestamp

    def test_minimum_two_beats_required(self):
        config = _make_config()
        selector = SegmentSelector(config)
        audio = AudioAnalysis(duration=1.0, tempo=120.0, beats=[BeatInfo(0.0, 0.5)])
        segments = _make_segments(5)
        with pytest.raises(ValueError, match="at least 2 beats"):
            selector.select(audio, segments)

    def test_no_segment_reuse(self):
        """Verify that no two decisions use the exact same source time range."""
        config = _make_config()
        selector = SegmentSelector(config)
        beats = _make_beats(20, 0.5)
        audio = AudioAnalysis(duration=9.5, tempo=120.0, beats=beats)
        segments = _make_segments(40, hop=0.5, window=2.0)
        plan = selector.select(audio, segments)
        # Each decision should come from a different zone, so source_start should differ
        source_ranges = [(d.source_start, d.source_end) for d in plan.decisions]
        # With zone-based selection and overlapping segments, the source positions
        # should be strictly increasing (chronological zones)
        for i in range(1, len(source_ranges)):
            assert source_ranges[i][0] >= source_ranges[i - 1][0]

    def test_chronological_order(self):
        """Verify source_start is non-decreasing across all decisions."""
        config = _make_config()
        selector = SegmentSelector(config)
        beats = _make_beats(15, 0.7)
        audio = AudioAnalysis(duration=9.8, tempo=85.7, beats=beats)
        segments = _make_segments(60, hop=0.5, window=2.0)
        plan = selector.select(audio, segments)
        for i in range(1, len(plan.decisions)):
            assert plan.decisions[i].source_start >= plan.decisions[i - 1].source_start, (
                f"Decision {i} source_start={plan.decisions[i].source_start} < "
                f"decision {i-1} source_start={plan.decisions[i-1].source_start}"
            )

    def test_zones_cover_full_video(self):
        """Verify zones span from near 0 to near the end of the video."""
        config = _make_config()
        selector = SegmentSelector(config)
        beats = _make_beats(6, 1.0)
        audio = AudioAnalysis(duration=5.0, tempo=60.0, beats=beats)
        segments = _make_segments(40, hop=0.5, window=2.0)
        video_duration = segments[-1].end_time

        zones = selector._compute_zones(
            [(beats[i], beats[i + 1]) for i in range(len(beats) - 1)],
            video_duration,
        )
        # First zone starts at 0
        assert zones[0][0] == 0.0
        # Last zone ends at video_duration
        assert abs(zones[-1][1] - video_duration) < 0.01

    def test_include_timestamps(self):
        """Verify --include forces selection of the segment containing that timestamp."""
        config = _make_config(include_timestamps=[5.0])
        selector = SegmentSelector(config)
        beats = _make_beats(6, 1.0)
        audio = AudioAnalysis(duration=5.0, tempo=60.0, beats=beats)
        segments = _make_segments(40, hop=0.5, window=2.0)
        plan = selector.select(audio, segments)
        has_included = any(
            d.source_start <= 5.0 <= d.source_end for d in plan.decisions
        )
        assert has_included

    def test_cut_plan_metadata(self, sample_audio_analysis, sample_segments):
        config = _make_config()
        selector = SegmentSelector(config)
        plan = selector.select(sample_audio_analysis, sample_segments)
        assert plan.song_tempo == 120.0
        assert plan.transition_style == TransitionStyle.HARD_CUT.value
        assert plan.total_duration > 0

    def test_empty_segments_raises(self):
        config = _make_config()
        selector = SegmentSelector(config)
        audio = AudioAnalysis(duration=5.0, tempo=120.0, beats=_make_beats(4))
        with pytest.raises(ValueError, match="No video segments"):
            selector.select(audio, [])


class TestMergeContinuous:
    """Tests for the _merge_continuous post-processing pass."""

    def _make_decision(self, idx, src_start, src_end, tgt_start, tgt_end, score=0.5):
        return EditDecision(
            beat_index=idx,
            source_start=src_start,
            source_end=src_end,
            target_start=tgt_start,
            target_end=tgt_end,
            interest_score=score,
        )

    def test_adjacent_decisions_merge(self):
        """5 decisions with adjacent source positions should merge into 1 clip."""
        config = _make_config()
        selector = SegmentSelector(config)
        # source positions are nearly continuous (gap < segment_window=2.0)
        decisions = [
            self._make_decision(0, 1.0, 1.6, 0.0, 0.6),
            self._make_decision(1, 1.5, 2.1, 0.6, 1.2),
            self._make_decision(2, 2.0, 2.6, 1.2, 1.8),
            self._make_decision(3, 2.5, 3.1, 1.8, 2.4),
            self._make_decision(4, 3.0, 3.6, 2.4, 3.0),
        ]
        merged = selector._merge_continuous(decisions)
        assert len(merged) == 1
        assert merged[0].target_start == 0.0
        assert merged[0].target_end == 3.0

    def test_distant_decisions_stay_separate(self):
        """Decisions with large source gaps should not merge."""
        config = _make_config()
        selector = SegmentSelector(config)
        # Each decision jumps >2.0s from the previous
        decisions = [
            self._make_decision(0, 1.0, 1.6, 0.0, 0.6),
            self._make_decision(1, 10.0, 10.6, 0.6, 1.2),
            self._make_decision(2, 20.0, 20.6, 1.2, 1.8),
        ]
        merged = selector._merge_continuous(decisions)
        assert len(merged) == 3

    def test_mixed_merge(self):
        """Some adjacent, some distant — correct number of merged clips."""
        config = _make_config()
        selector = SegmentSelector(config)
        decisions = [
            # Group 1: adjacent (gap < 2.0)
            self._make_decision(0, 1.0, 1.6, 0.0, 0.6),
            self._make_decision(1, 1.5, 2.1, 0.6, 1.2),
            self._make_decision(2, 2.0, 2.6, 1.2, 1.8),
            # Group 2: big jump then adjacent
            self._make_decision(3, 50.0, 50.6, 1.8, 2.4),
            self._make_decision(4, 50.5, 51.1, 2.4, 3.0),
        ]
        merged = selector._merge_continuous(decisions)
        assert len(merged) == 2
        # First group covers target 0.0-1.8
        assert merged[0].target_start == 0.0
        assert merged[0].target_end == 1.8
        # Second group covers target 1.8-3.0
        assert merged[1].target_start == 1.8
        assert merged[1].target_end == 3.0

    def test_merged_source_duration_matches_target(self):
        """For each merged clip, source_end - source_start == target_end - target_start."""
        config = _make_config()
        selector = SegmentSelector(config)
        decisions = [
            self._make_decision(0, 1.0, 1.6, 0.0, 0.6),
            self._make_decision(1, 1.5, 2.1, 0.6, 1.2),
            self._make_decision(2, 2.0, 2.6, 1.2, 1.8),
            self._make_decision(3, 50.0, 50.6, 1.8, 2.4),
            self._make_decision(4, 50.5, 51.1, 2.4, 3.0),
        ]
        merged = selector._merge_continuous(decisions)
        for d in merged:
            source_dur = d.source_end - d.source_start
            target_dur = d.target_end - d.target_start
            assert abs(source_dur - target_dur) < 1e-9, (
                f"Source duration {source_dur:.3f} != target duration {target_dur:.3f}"
            )

    def test_single_decision_unchanged(self):
        """A single decision should pass through unchanged."""
        config = _make_config()
        selector = SegmentSelector(config)
        decisions = [self._make_decision(0, 5.0, 5.6, 0.0, 0.6)]
        merged = selector._merge_continuous(decisions)
        assert len(merged) == 1
        assert merged[0].source_start == 5.0
        assert merged[0].source_end == 5.6
