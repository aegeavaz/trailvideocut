from pathlib import Path

import numpy as np
import pytest

from smartcut.audio.models import AudioAnalysis, BeatInfo
from smartcut.config import SegmentPreference, SmartCutConfig, TransitionStyle
from smartcut.editor.selector import SegmentSelector
from smartcut.video.models import InterestScore, VideoSegment


def _make_config(**overrides) -> SmartCutConfig:
    defaults = dict(
        video_path=Path("test.mp4"),
        audio_path=Path("test.wav"),
    )
    defaults.update(overrides)
    return SmartCutConfig(**defaults)


def _make_segments(n: int = 20, duration: float = 2.0) -> list[VideoSegment]:
    segments = []
    for i in range(n):
        interest = InterestScore(
            optical_flow=float(i) / n,
            color_change=float(n - i) / n,
            edge_variance=0.5,
            brightness_change=0.3,
        )
        segments.append(
            VideoSegment(
                start_time=i * duration,
                end_time=(i + 1) * duration,
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
    def test_produces_correct_number_of_decisions(self, sample_audio_analysis, sample_segments):
        config = _make_config()
        selector = SegmentSelector(config)
        plan = selector.select(sample_audio_analysis, sample_segments)
        # Should have N-1 decisions for N beats
        assert len(plan.decisions) == len(sample_audio_analysis.beats) - 1

    def test_decisions_cover_full_timeline(self, sample_audio_analysis, sample_segments):
        config = _make_config()
        selector = SegmentSelector(config)
        plan = selector.select(sample_audio_analysis, sample_segments)
        # First decision starts at first beat
        assert plan.decisions[0].target_start == sample_audio_analysis.beats[0].timestamp
        # Last decision ends at last beat
        assert plan.decisions[-1].target_end == sample_audio_analysis.beats[-1].timestamp

    def test_minimum_two_beats_required(self):
        config = _make_config()
        selector = SegmentSelector(config)
        audio = AudioAnalysis(duration=1.0, tempo=120.0, beats=[BeatInfo(0.0, 0.5)])
        segments = _make_segments(5)
        with pytest.raises(ValueError, match="at least 2 beats"):
            selector.select(audio, segments)

    def test_high_action_prefers_high_interest(self):
        config = _make_config(segment_preference=SegmentPreference.HIGH_ACTION)
        selector = SegmentSelector(config)
        beats = _make_beats(4, 1.0)
        audio = AudioAnalysis(duration=3.0, tempo=60.0, beats=beats)
        segments = _make_segments(10, 2.0)
        plan = selector.select(audio, segments)
        # With HIGH_ACTION, average interest should be relatively high
        avg_interest = np.mean([d.interest_score for d in plan.decisions])
        assert avg_interest > 0.2

    def test_include_timestamps_reserves_segments(self):
        config = _make_config(include_timestamps=[5.0])
        selector = SegmentSelector(config)
        beats = _make_beats(6, 1.0)
        audio = AudioAnalysis(duration=5.0, tempo=60.0, beats=beats)
        segments = _make_segments(10, 2.0)
        plan = selector.select(audio, segments)
        # The segment containing timestamp 5.0 should appear somewhere in decisions
        has_included = any(
            d.source_start <= 5.0 <= d.source_end for d in plan.decisions
        )
        assert has_included

    def test_chronological_preference(self):
        config = _make_config(segment_preference=SegmentPreference.CHRONOLOGICAL)
        selector = SegmentSelector(config)
        beats = _make_beats(6, 1.0)
        audio = AudioAnalysis(duration=5.0, tempo=60.0, beats=beats)
        segments = _make_segments(20, 2.0)
        plan = selector.select(audio, segments)
        assert len(plan.decisions) == 5

    def test_cut_plan_metadata(self, sample_audio_analysis, sample_segments):
        config = _make_config()
        selector = SegmentSelector(config)
        plan = selector.select(sample_audio_analysis, sample_segments)
        assert plan.song_tempo == 120.0
        assert plan.transition_style == TransitionStyle.HARD_CUT.value
        assert plan.total_duration > 0
