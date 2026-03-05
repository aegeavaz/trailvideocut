from pathlib import Path

import numpy as np
import pytest

from smartcut.audio.models import AudioAnalysis, BeatInfo, MusicSection
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


def _make_sections_for_beats(beats: list[BeatInfo], energy: float = 0.5) -> list[MusicSection]:
    """Create a single section spanning all beats with given energy."""
    return [MusicSection(
        label="section",
        start_time=beats[0].timestamp,
        end_time=beats[-1].timestamp,
        energy=energy,
    )]


class TestSegmentSelector:
    def test_clips_selected_le_beat_intervals(self, sample_audio_analysis, sample_segments):
        config = _make_config()
        selector = SegmentSelector(config)
        plan = selector.select(sample_audio_analysis, sample_segments)
        n_intervals = len(sample_audio_analysis.beats) - 1
        assert plan.clips_selected <= n_intervals
        assert len(plan.decisions) <= plan.clips_selected

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
        """Verify source positions are non-decreasing (chronological selection)."""
        config = _make_config()
        selector = SegmentSelector(config)
        beats = _make_beats(20, 0.5)
        audio = AudioAnalysis(
            duration=9.5, tempo=120.0, beats=beats,
            sections=_make_sections_for_beats(beats),
        )
        segments = _make_segments(40, hop=0.5, window=2.0)
        plan = selector.select(audio, segments)
        source_ranges = [(d.source_start, d.source_end) for d in plan.decisions]
        for i in range(1, len(source_ranges)):
            assert source_ranges[i][0] >= source_ranges[i - 1][0]

    def test_chronological_order(self):
        """Verify source_start is non-decreasing across all decisions."""
        config = _make_config()
        selector = SegmentSelector(config)
        beats = _make_beats(15, 0.7)
        audio = AudioAnalysis(
            duration=9.8, tempo=85.7, beats=beats,
            sections=_make_sections_for_beats(beats),
        )
        segments = _make_segments(60, hop=0.5, window=2.0)
        plan = selector.select(audio, segments)
        for i in range(1, len(plan.decisions)):
            assert plan.decisions[i].source_start >= plan.decisions[i - 1].source_start, (
                f"Decision {i} source_start={plan.decisions[i].source_start} < "
                f"decision {i-1} source_start={plan.decisions[i-1].source_start}"
            )

    def test_include_timestamps(self):
        """Verify --include forces selection of the segment containing that timestamp."""
        config = _make_config(include_timestamps=[5.0])
        selector = SegmentSelector(config)
        beats = _make_beats(6, 1.0)
        audio = AudioAnalysis(
            duration=5.0, tempo=60.0, beats=beats,
            sections=_make_sections_for_beats(beats),
        )
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
        assert plan.score_cv >= 0.0

    def test_empty_segments_raises(self):
        config = _make_config()
        selector = SegmentSelector(config)
        audio = AudioAnalysis(duration=5.0, tempo=120.0, beats=_make_beats(4))
        with pytest.raises(ValueError, match="No video segments"):
            selector.select(audio, [])

    def test_explicit_cut_points(self):
        """When cut_points are provided, clips_selected is based on cut_points not audio.beats."""
        config = _make_config()
        selector = SegmentSelector(config)
        all_beats = _make_beats(20, 0.5)
        cut_points = [all_beats[0], all_beats[4], all_beats[8], all_beats[12], all_beats[19]]
        audio = AudioAnalysis(
            duration=9.5, tempo=120.0, beats=all_beats,
            sections=_make_sections_for_beats(all_beats),
        )
        segments = _make_segments(40, hop=0.5, window=2.0)
        plan = selector.select(audio, segments, cut_points=cut_points)
        assert plan.clips_selected <= len(cut_points) - 1


class TestGlobalSelection:
    """Tests for the global score-ranked selection algorithm."""

    def test_global_selection_prefers_high_scores(self):
        """Top-scoring segments should be selected over low-scoring ones."""
        config = _make_config()
        selector = SegmentSelector(config)

        # Create segments: most have low scores, a few have very high scores
        segments = []
        for i in range(50):
            t = i * 0.5
            if i in (10, 25, 40):  # 3 high-scoring segments
                score = InterestScore(optical_flow=1.0, color_change=1.0,
                                      edge_variance=1.0, brightness_change=1.0)
            else:
                score = InterestScore(optical_flow=0.1, color_change=0.1,
                                      edge_variance=0.1, brightness_change=0.1)
            segments.append(VideoSegment(start_time=t, end_time=t + 2.0, interest=score))

        beats = _make_beats(6, 1.0)
        audio = AudioAnalysis(
            duration=5.0, tempo=60.0, beats=beats,
            sections=_make_sections_for_beats(beats, energy=0.5),
        )
        plan = selector.select(audio, segments)
        # All selected clip scores should be > 0.1 (low score baseline)
        avg_score = sum(d.interest_score for d in plan.decisions) / len(plan.decisions)
        assert avg_score > 0.1, f"Average score {avg_score:.3f} is too low"

    def test_coverage_zones_prevent_clustering(self):
        """Coverage zones should ensure clips from later parts of video even when
        all high scores are at the start."""
        config = _make_config()
        selector = SegmentSelector(config)

        # All high scores concentrated at the start
        segments = []
        for i in range(60):
            t = i * 0.5
            if t < 5.0:
                score = InterestScore(optical_flow=1.0, color_change=1.0,
                                      edge_variance=1.0, brightness_change=1.0)
            else:
                score = InterestScore(optical_flow=0.3, color_change=0.3,
                                      edge_variance=0.3, brightness_change=0.3)
            segments.append(VideoSegment(start_time=t, end_time=t + 2.0, interest=score))

        beats = _make_beats(12, 0.8)
        audio = AudioAnalysis(
            duration=8.8, tempo=75.0, beats=beats,
            sections=_make_sections_for_beats(beats, energy=0.5),
        )
        plan = selector.select(audio, segments)

        # Coverage zones guarantee clips from later parts of the video
        max_source_end = max(d.source_end for d in plan.decisions)
        assert max_source_end > 5.0, "All clips clustered at the beginning"

    def test_coverage_zones_ensure_spread(self):
        """With uniform scores, coverage zones guarantee clips from each region."""
        config = _make_config()
        selector = SegmentSelector(config)

        # 200 segments over 100s, all with identical scores
        segments = []
        for i in range(200):
            t = i * 0.5
            score = InterestScore(optical_flow=0.5, color_change=0.5,
                                  edge_variance=0.5, brightness_change=0.5)
            segments.append(VideoSegment(start_time=t, end_time=t + 2.0, interest=score))

        beats = _make_beats(20, 1.0)
        sections = [MusicSection(label="all", start_time=0.0, end_time=19.0, energy=0.5)]
        audio = AudioAnalysis(duration=19.0, tempo=60.0, beats=beats, sections=sections)
        plan = selector.select(audio, segments)

        # With 19 intervals, coverage_zone_count = max(4, 19//8) = 4 zones of ~25s
        # Verify clips span the video: at least one clip from past the midpoint
        mid = 19.0 / 2
        has_late_clip = any(d.source_start >= mid for d in plan.decisions)
        assert has_late_clip, "No clips from the second half of the video"

    def test_include_timestamps_with_global_selection(self):
        """Must-include timestamps should be in the output even if not top-scored."""
        include_ts = 15.0
        config = _make_config(include_timestamps=[include_ts])
        selector = SegmentSelector(config)

        # Create segments where t=15s has a low score
        segments = []
        for i in range(60):
            t = i * 0.5
            if abs(t + 1.0 - include_ts) < 1.5:  # Near include timestamp
                score = InterestScore(optical_flow=0.05, color_change=0.05,
                                      edge_variance=0.05, brightness_change=0.05)
            else:
                score = InterestScore(optical_flow=0.8, color_change=0.8,
                                      edge_variance=0.8, brightness_change=0.8)
            segments.append(VideoSegment(start_time=t, end_time=t + 2.0, interest=score))

        beats = _make_beats(10, 1.0)
        audio = AudioAnalysis(
            duration=9.0, tempo=60.0, beats=beats,
            sections=_make_sections_for_beats(beats, energy=0.5),
        )
        plan = selector.select(audio, segments)
        has_included = any(
            d.source_start <= include_ts <= d.source_end for d in plan.decisions
        )
        assert has_included, f"Include timestamp {include_ts}s not found in output"


class TestQualityAdaptive:
    """Tests for quality-adaptive cut count."""

    def test_quality_adaptive_reduces_clips(self):
        """Uniform scores (low CV) should produce fewer clips."""
        config = _make_config(quality_cv_threshold=0.4, quality_max_reduction=0.5)
        selector = SegmentSelector(config)

        # All segments have identical scores -> CV = 0
        segments = []
        for i in range(60):
            t = i * 0.5
            score = InterestScore(optical_flow=0.5, color_change=0.5,
                                  edge_variance=0.5, brightness_change=0.5)
            segments.append(VideoSegment(start_time=t, end_time=t + 2.0, interest=score))

        beats = _make_beats(20, 0.5)
        audio = AudioAnalysis(
            duration=9.5, tempo=120.0, beats=beats,
            sections=_make_sections_for_beats(beats, energy=0.5),
        )
        plan = selector.select(audio, segments)
        n_intervals = len(beats) - 1
        assert plan.clips_selected < n_intervals, (
            f"Expected fewer clips than {n_intervals} intervals, got {plan.clips_selected}"
        )

    def test_quality_adaptive_preserves_high_energy(self):
        """When merging intervals, high-energy sections should keep fast cuts."""
        config = _make_config(quality_cv_threshold=0.4, quality_max_reduction=0.5)
        selector = SegmentSelector(config)

        # Uniform scores -> will trigger reduction
        segments = []
        for i in range(60):
            t = i * 0.5
            score = InterestScore(optical_flow=0.5, color_change=0.5,
                                  edge_variance=0.5, brightness_change=0.5)
            segments.append(VideoSegment(start_time=t, end_time=t + 2.0, interest=score))

        beats = _make_beats(20, 0.5)
        sections = [
            MusicSection(label="calm", start_time=0.0, end_time=5.0, energy=0.2),
            MusicSection(label="intense", start_time=5.0, end_time=9.5, energy=0.9),
        ]
        audio = AudioAnalysis(duration=9.5, tempo=120.0, beats=beats, sections=sections)
        plan = selector.select(audio, segments)

        # Decisions in the high-energy section should have shorter durations
        # (more cuts) than low-energy section
        calm_durs = [
            d.target_end - d.target_start for d in plan.decisions
            if d.target_start < 5.0
        ]
        intense_durs = [
            d.target_end - d.target_start for d in plan.decisions
            if d.target_start >= 5.0
        ]
        if calm_durs and intense_durs:
            # Calm section should have merged to longer clips on average
            avg_calm = sum(calm_durs) / len(calm_durs)
            avg_intense = sum(intense_durs) / len(intense_durs)
            assert avg_calm >= avg_intense, (
                f"Expected calm avg duration {avg_calm:.2f} >= intense {avg_intense:.2f}"
            )

    def test_quality_adaptive_no_change_for_diverse(self):
        """High CV (diverse scores) should not reduce clip count."""
        config = _make_config(quality_cv_threshold=0.4, quality_max_reduction=0.5)
        selector = SegmentSelector(config)

        # Create highly varied scores
        segments = []
        for i in range(60):
            t = i * 0.5
            # Alternate between very high and very low scores
            if i % 2 == 0:
                score = InterestScore(optical_flow=1.0, color_change=1.0,
                                      edge_variance=1.0, brightness_change=1.0)
            else:
                score = InterestScore(optical_flow=0.01, color_change=0.01,
                                      edge_variance=0.01, brightness_change=0.01)
            segments.append(VideoSegment(start_time=t, end_time=t + 2.0, interest=score))

        beats = _make_beats(10, 0.5)
        audio = AudioAnalysis(
            duration=4.5, tempo=120.0, beats=beats,
            sections=_make_sections_for_beats(beats, energy=0.5),
        )
        plan = selector.select(audio, segments)
        n_intervals = len(beats) - 1
        assert plan.clips_selected == n_intervals, (
            f"Expected {n_intervals} clips (no reduction), got {plan.clips_selected}"
        )

    def test_merge_cap_prevents_long_intervals(self):
        """Merging low-energy intervals should stop before exceeding max_segment_duration."""
        max_dur = 4.0
        config = _make_config(
            quality_cv_threshold=0.4,
            quality_max_reduction=0.5,
            max_segment_duration=max_dur,
        )
        selector = SegmentSelector(config)

        # Test _merge_low_energy_intervals directly to isolate from _merge_continuous
        beats = _make_beats(30, 0.5)  # 29 intervals of 0.5s each
        sections = [MusicSection(label="all", start_time=0.0, end_time=14.5, energy=0.3)]
        intervals = [(beats[i], beats[i + 1]) for i in range(len(beats) - 1)]

        # Target fewer intervals to force merging
        merged = selector._merge_low_energy_intervals(intervals, sections, target_count=5)

        # No merged interval should exceed max_segment_duration
        for start_beat, end_beat in merged:
            dur = end_beat.timestamp - start_beat.timestamp
            assert dur <= max_dur + 0.01, (
                f"Merged interval {dur:.2f}s exceeds max {max_dur}s"
            )

        # Should have more intervals than target since merging stopped early
        assert len(merged) >= 5, "Should have at least target_count intervals"


class TestEnergyWeightedScoring:
    """Tests for energy-weighted composite scoring."""

    def test_energy_weighted_high_energy_prefers_motion(self):
        """High-energy sections should prefer segments with high optical flow."""
        # Segment A: high optical_flow, low edge_variance
        a = InterestScore(optical_flow=0.9, color_change=0.3, edge_variance=0.1, brightness_change=0.3)
        # Segment B: low optical_flow, high edge_variance
        b = InterestScore(optical_flow=0.1, color_change=0.3, edge_variance=0.9, brightness_change=0.3)

        # At high energy, A should score higher
        assert a.energy_weighted_composite(0.8) > b.energy_weighted_composite(0.8)
        # At standard composite, the difference should be smaller or reversed
        diff_high = a.energy_weighted_composite(0.8) - b.energy_weighted_composite(0.8)
        diff_mid = a.composite - b.composite
        assert diff_high > diff_mid

    def test_energy_weighted_low_energy_prefers_scenic(self):
        """Low-energy sections should prefer segments with high edge variance."""
        # Segment A: high optical_flow, low edge_variance (action)
        a = InterestScore(optical_flow=0.9, color_change=0.3, edge_variance=0.1, brightness_change=0.3)
        # Segment B: low optical_flow, high edge_variance (scenic)
        b = InterestScore(optical_flow=0.1, color_change=0.3, edge_variance=0.9, brightness_change=0.3)

        # At low energy, B should score higher
        assert b.energy_weighted_composite(0.2) > a.energy_weighted_composite(0.2)

    def test_energy_weighted_mid_energy_equals_composite(self):
        """Mid-energy should return the standard composite."""
        s = InterestScore(optical_flow=0.5, color_change=0.5, edge_variance=0.5, brightness_change=0.5)
        assert s.energy_weighted_composite(0.5) == s.composite

    def test_score_cv_in_cut_plan(self):
        """CutPlan should include score_cv metric."""
        config = _make_config()
        selector = SegmentSelector(config)
        beats = _make_beats(6, 1.0)
        audio = AudioAnalysis(
            duration=5.0, tempo=60.0, beats=beats,
            sections=_make_sections_for_beats(beats),
        )
        segments = _make_segments(40, hop=0.5, window=2.0)
        plan = selector.select(audio, segments)
        assert hasattr(plan, 'score_cv')
        assert plan.score_cv >= 0.0


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
            self._make_decision(0, 1.0, 1.6, 0.0, 0.6),
            self._make_decision(1, 1.5, 2.1, 0.6, 1.2),
            self._make_decision(2, 2.0, 2.6, 1.2, 1.8),
            self._make_decision(3, 50.0, 50.6, 1.8, 2.4),
            self._make_decision(4, 50.5, 51.1, 2.4, 3.0),
        ]
        merged = selector._merge_continuous(decisions)
        assert len(merged) == 2
        assert merged[0].target_start == 0.0
        assert merged[0].target_end == 1.8
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

    def test_merge_respects_max_segment_duration(self):
        """Merging should stop before exceeding max_segment_duration."""
        config = _make_config(max_segment_duration=4.0)
        selector = SegmentSelector(config)
        # 20 adjacent decisions: source gap 0.4s < threshold 2.0s, each 0.6s target
        decisions = [
            self._make_decision(i, 1.0 + i * 0.5, 1.6 + i * 0.5, i * 0.6, (i + 1) * 0.6)
            for i in range(20)
        ]
        merged = selector._merge_continuous(decisions)
        # Total target = 12.0s, max_segment_duration = 4.0s -> at least 3 clips
        assert len(merged) >= 3, f"Expected at least 3 clips, got {len(merged)}"
        for d in merged:
            dur = d.target_end - d.target_start
            assert dur <= 4.0 + 1e-9, f"Clip duration {dur:.2f}s exceeds max 4.0s"
            source_dur = d.source_end - d.source_start
            target_dur = d.target_end - d.target_start
            assert abs(source_dur - target_dur) < 1e-9, (
                f"Source duration {source_dur:.3f} != target duration {target_dur:.3f}"
            )

    def test_merge_no_source_overlap_on_duration_break(self):
        """When duration cap breaks a continuous group, clips should not overlap in source."""
        config = _make_config(max_segment_duration=4.0)
        selector = SegmentSelector(config)
        decisions = [
            self._make_decision(i, 1.0 + i * 0.5, 1.6 + i * 0.5, i * 0.6, (i + 1) * 0.6)
            for i in range(20)
        ]
        merged = selector._merge_continuous(decisions)
        for i in range(1, len(merged)):
            assert merged[i].source_start >= merged[i - 1].source_end - 1e-9, (
                f"Clip {i} source [{merged[i].source_start:.1f}, {merged[i].source_end:.1f}] "
                f"overlaps with clip {i-1} [{merged[i-1].source_start:.1f}, {merged[i-1].source_end:.1f}]"
            )

    def test_merge_no_source_overlap_across_groups(self):
        """Source overlap between groups is eliminated when a gap-break group
        falls inside the previous group's advanced source range."""
        config = _make_config(max_segment_duration=4.0)
        selector = SegmentSelector(config)
        # Group 1: 10 adjacent decisions (source ~1.0-6.0, target 0.0-6.0)
        group1 = [
            self._make_decision(i, 1.0 + i * 0.5, 1.6 + i * 0.5, i * 0.6, (i + 1) * 0.6)
            for i in range(10)
        ]
        # Group 2: gap-break decision whose source falls inside group1's advanced range
        group2 = [self._make_decision(10, 3.0, 3.6, 6.0, 6.6)]
        merged = selector._merge_continuous(group1 + group2)
        for i in range(1, len(merged)):
            assert merged[i].source_start >= merged[i - 1].source_end - 1e-9, (
                f"Clip {i} source [{merged[i].source_start:.1f}, {merged[i].source_end:.1f}] "
                f"overlaps with clip {i-1} [{merged[i-1].source_start:.1f}, {merged[i-1].source_end:.1f}]"
            )


class TestClusterDensityLimit:
    """Tests for cluster density limiting in segment selection."""

    def test_no_excessive_same_region_clips(self):
        """Cluster density limit should prevent selecting too many segments
        from the same source region, even when that region has high scores."""
        max_dur = 8.0
        config = _make_config(max_segment_duration=max_dur, segment_window=2.0, segment_hop=0.5)
        selector = SegmentSelector(config)

        # 305 segments over 152.5s (hop=0.5, window=2.0)
        # A 10s cluster at t=50-60 has very high scores
        segments = []
        for i in range(305):
            t = i * 0.5
            if 50.0 <= t <= 60.0:
                score = InterestScore(optical_flow=1.0, color_change=1.0,
                                      edge_variance=1.0, brightness_change=1.0)
            else:
                score = InterestScore(optical_flow=0.3, color_change=0.3,
                                      edge_variance=0.3, brightness_change=0.3)
            segments.append(VideoSegment(start_time=t, end_time=t + 2.0, interest=score))

        sorted_segments = sorted(segments, key=lambda s: s.midpoint)
        midpoints = [s.midpoint for s in sorted_segments]
        n = 51
        sections = [MusicSection(label="all", start_time=0.0, end_time=152.5, energy=0.5)]
        video_duration = 152.5

        selected = selector._select_top_segments(
            sorted_segments, midpoints, sections, n, video_duration,
            include_segments=[],
        )

        # Count how many selected segments have midpoints in the cluster region
        cluster_count = sum(1 for s in selected if 50.0 <= s.midpoint <= 60.0)

        # avg_interval = 152.5/51 ≈ 2.99, max_from_region = int(8.0/2.99) = 2
        # cluster_range = 4.0, so within any 8s window at most 2 segments.
        # The 10s cluster spans ~2.5 cluster windows, so at most ~5 segments.
        # Without the limit, all 21 high-score segments would be selected.
        assert cluster_count <= 5, (
            f"Selected {cluster_count} segments from cluster region [50, 60], "
            f"expected at most 5 (without limit would be ~21)"
        )
