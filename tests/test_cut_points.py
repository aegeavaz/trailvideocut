
from trailvideocut.audio.energy_curve import EnergyTransition
from trailvideocut.audio.models import BeatInfo, MusicSection
from trailvideocut.editor.cut_points import (
    energy_to_density,
    select_cut_points,
    select_cut_points_for_section,
)


def _make_beats(n: int, interval: float = 0.5, start: float = 0.0) -> list[BeatInfo]:
    return [
        BeatInfo(
            timestamp=start + i * interval,
            strength=0.8 if i % 4 == 0 else 0.5,
            is_downbeat=i % 4 == 0,
        )
        for i in range(n)
    ]


class TestEnergyToDensity:
    def test_max_energy_gives_max_density(self):
        density = energy_to_density(energy=1.0, tempo=120.0, min_segment=0.5, max_segment=8.0)
        # max_density = min(120/60, 1/0.5) = min(2.0, 2.0) = 2.0
        assert density == 2.0

    def test_max_density_capped_by_min_segment(self):
        """When min_segment makes beat-rate density impossible, cap max_density."""
        density = energy_to_density(energy=1.0, tempo=160.0, min_segment=1.0, max_segment=8.0)
        # max_density = min(160/60, 1/1.0) = min(2.67, 1.0) = 1.0
        assert density == 1.0

    def test_zero_energy_gives_min_density(self):
        density = energy_to_density(energy=0.0, tempo=120.0, min_segment=0.5, max_segment=8.0)
        expected_min = 1.0 / 8.0  # 0.125
        assert density == expected_min

    def test_mid_energy_interpolates(self):
        density = energy_to_density(energy=0.5, tempo=120.0, min_segment=0.5, max_segment=8.0)
        min_d = 1.0 / 8.0
        max_d = min(120.0 / 60.0, 1.0 / 0.5)  # 2.0
        expected = min_d + (0.5 ** 2) * (max_d - min_d)
        assert abs(density - expected) < 1e-9

    def test_density_increases_with_energy(self):
        d_low = energy_to_density(0.2, 120.0, 0.5, 8.0)
        d_high = energy_to_density(0.8, 120.0, 0.5, 8.0)
        assert d_high > d_low


class TestSelectCutPointsForSection:
    def test_empty_beats_returns_empty(self):
        result = select_cut_points_for_section([], 2.0, 0.25, 8.0)
        assert result == []

    def test_respects_min_segment(self):
        beats = _make_beats(20, interval=0.2)  # beats every 0.2s
        # High density that wants every beat, but min_segment=0.5 prevents it
        result = select_cut_points_for_section(beats, 5.0, min_segment=0.5, max_segment=8.0)
        for i in range(1, len(result)):
            gap = result[i].timestamp - result[i - 1].timestamp
            assert gap >= 0.5 - 0.01, f"Gap {gap} < min_segment 0.5"

    def test_respects_max_segment(self):
        beats = _make_beats(10, interval=1.0)  # beats every 1s
        # Very low density (one cut every 20s), but max_segment=3.0 forces more
        result = select_cut_points_for_section(beats, 0.05, min_segment=0.25, max_segment=3.0)
        for i in range(1, len(result)):
            gap = result[i].timestamp - result[i - 1].timestamp
            assert gap <= 3.0 + 0.01, f"Gap {gap} > max_segment 3.0"

    def test_high_density_keeps_more_beats(self):
        beats = _make_beats(20, interval=0.5)  # 10s of beats
        low_cuts = select_cut_points_for_section(beats, 0.5, 0.25, 8.0)
        high_cuts = select_cut_points_for_section(beats, 2.0, 0.25, 8.0)
        assert len(high_cuts) > len(low_cuts)

    def test_prefers_downbeats(self):
        # Create beats where beat 0 is downbeat, 1-3 are not, 4 is downbeat
        beats = [
            BeatInfo(timestamp=0.0, strength=0.8, is_downbeat=True),
            BeatInfo(timestamp=0.5, strength=0.5, is_downbeat=False),
            BeatInfo(timestamp=1.0, strength=0.5, is_downbeat=False),
            BeatInfo(timestamp=1.5, strength=0.5, is_downbeat=False),
            BeatInfo(timestamp=2.0, strength=0.8, is_downbeat=True),
            BeatInfo(timestamp=2.5, strength=0.5, is_downbeat=False),
            BeatInfo(timestamp=3.0, strength=0.5, is_downbeat=False),
        ]
        # Density that wants a cut roughly every 1.5s — should prefer the downbeat at 2.0
        result = select_cut_points_for_section(beats, 0.67, 0.25, 8.0)
        timestamps = [b.timestamp for b in result]
        # First cut at 0.0, second should be near 1.5 but prefer 2.0 (downbeat)
        assert 2.0 in timestamps

    def test_prefers_strong_beats_over_weak(self):
        """A strong beat slightly after ideal time should win over a weak beat at ideal time."""
        beats = [
            BeatInfo(timestamp=0.0, strength=0.5, is_downbeat=True),
            BeatInfo(timestamp=1.5, strength=0.2, is_downbeat=False),  # weak, at ideal
            BeatInfo(timestamp=1.8, strength=0.9, is_downbeat=False),  # strong, slightly after
            BeatInfo(timestamp=3.0, strength=0.5, is_downbeat=False),
        ]
        # Density ~0.67 -> interval ~1.5s, ideal_next = 1.5
        result = select_cut_points_for_section(beats, 0.67, 0.25, 8.0)
        timestamps = [b.timestamp for b in result]
        # Strong beat at 1.8 should be preferred over weak beat at 1.5
        assert 1.8 in timestamps
        assert 1.5 not in timestamps

    def test_downbeat_bonus_in_scoring(self):
        """A moderate-strength downbeat should beat a slightly stronger non-downbeat."""
        beats = [
            BeatInfo(timestamp=0.0, strength=0.5, is_downbeat=True),
            BeatInfo(timestamp=1.5, strength=0.7, is_downbeat=False),  # stronger, not downbeat
            BeatInfo(timestamp=1.6, strength=0.6, is_downbeat=True),   # weaker, but downbeat
            BeatInfo(timestamp=3.0, strength=0.5, is_downbeat=False),
        ]
        # interval ~1.5s, both candidates are near ideal_next = 1.5
        result = select_cut_points_for_section(beats, 0.67, 0.25, 8.0)
        timestamps = [b.timestamp for b in result]
        # Downbeat at 1.6 should win due to 0.2 downbeat bonus
        assert 1.6 in timestamps

    def test_proximity_scoring_with_high_min_segment(self):
        """When min_segment > target_interval, proximity scoring should still work.

        Previously, ideal_next used uncapped target_interval, making proximity=0
        for all candidates and degrading to strength-only selection.
        """
        # Simulate 160 BPM with beats every ~0.37s, min_segment=1.0
        beats = _make_beats(20, interval=0.37, start=0.0)
        # High density that would produce target_interval < min_segment
        # effective_interval should be max(target_interval, min_segment) = 1.0
        result = select_cut_points_for_section(
            beats, target_density=2.7, min_segment=1.0, max_segment=8.0
        )
        # All gaps must respect min_segment
        for i in range(1, len(result)):
            gap = result[i].timestamp - result[i - 1].timestamp
            assert gap >= 1.0 - 0.01, f"Gap {gap} < min_segment 1.0"
        # Should still produce multiple cuts (not just first and last)
        assert len(result) >= 3


class TestSelectCutPoints:
    def test_empty_beats_returns_empty(self):
        sections = [MusicSection("verse", 0.0, 10.0, 0.5)]
        assert select_cut_points([], sections, 120.0, 0.25, 8.0) == []

    def test_empty_sections_returns_all_beats(self):
        beats = _make_beats(10, 0.5)
        result = select_cut_points(beats, [], 120.0, 0.25, 8.0)
        assert result == beats

    def test_high_energy_section_more_cuts_than_low(self):
        beats = _make_beats(40, interval=0.5, start=0.0)  # 0-20s
        sections = [
            MusicSection("verse", 0.0, 10.0, 0.3),   # low energy
            MusicSection("chorus", 10.0, 20.0, 0.9),  # high energy
        ]
        result = select_cut_points(beats, sections, 120.0, 0.25, 8.0)
        verse_cuts = [b for b in result if b.timestamp < 10.0]
        chorus_cuts = [b for b in result if 10.0 <= b.timestamp < 20.0]
        assert len(chorus_cuts) > len(verse_cuts)

    def test_section_boundary_no_duplicate(self):
        beats = _make_beats(20, interval=0.5)
        sections = [
            MusicSection("intro", 0.0, 5.0, 0.5),
            MusicSection("verse", 5.0, 10.0, 0.5),
        ]
        result = select_cut_points(beats, sections, 120.0, 0.25, 8.0)
        timestamps = [b.timestamp for b in result]
        # No duplicates
        assert len(timestamps) == len(set(timestamps))

    def test_section_boundary_respects_min_segment(self):
        beats = _make_beats(20, interval=0.5)
        sections = [
            MusicSection("intro", 0.0, 5.0, 1.0),
            MusicSection("verse", 5.0, 10.0, 1.0),
        ]
        result = select_cut_points(beats, sections, 120.0, 0.25, 8.0)
        for i in range(1, len(result)):
            gap = result[i].timestamp - result[i - 1].timestamp
            assert gap >= 0.25 - 0.01

    def test_max_segment_with_non_aligned_beats(self):
        """Beats at 0.42s intervals with max_segment=3.0 — all gaps must be ≤ 3.0."""
        beats = _make_beats(50, interval=0.42)  # 21s of beats
        # Very low density to trigger forced cuts
        result = select_cut_points_for_section(beats, 0.1, min_segment=1.0, max_segment=3.0)
        for i in range(1, len(result)):
            gap = result[i].timestamp - result[i - 1].timestamp
            assert gap <= 3.0 + 0.01, (
                f"Gap {gap:.3f}s between cuts at {result[i-1].timestamp:.3f} "
                f"and {result[i].timestamp:.3f} exceeds max_segment 3.0"
            )

    def test_candidate_window_preserves_valid_candidates(self):
        """Valid candidates in window should not be overwritten by an oversized one."""
        # Set up beats so the window collects valid candidates before hitting one at >= max_segment
        beats = [
            BeatInfo(timestamp=0.0, strength=0.8, is_downbeat=True),
            BeatInfo(timestamp=1.5, strength=0.7, is_downbeat=False),
            BeatInfo(timestamp=2.5, strength=0.6, is_downbeat=False),  # valid candidate
            BeatInfo(timestamp=3.0, strength=0.5, is_downbeat=False),  # at max_segment boundary
            BeatInfo(timestamp=4.0, strength=0.5, is_downbeat=False),
        ]
        result = select_cut_points_for_section(beats, 0.5, min_segment=1.0, max_segment=3.0)
        for i in range(1, len(result)):
            gap = result[i].timestamp - result[i - 1].timestamp
            assert gap <= 3.0 + 0.01, (
                f"Gap {gap:.3f}s exceeds max_segment 3.0"
            )

    def test_max_segment_across_section_boundary(self):
        """Cross-section gaps must not exceed max_segment."""
        beats = _make_beats(30, interval=0.5)  # 15s of beats
        # Two sections with a gap in beat selection that could cross max_segment
        sections = [
            MusicSection("intro", 0.0, 5.0, 0.1),   # very low energy -> few cuts
            MusicSection("verse", 5.0, 15.0, 0.1),   # very low energy -> few cuts
        ]
        result = select_cut_points(beats, sections, 120.0, min_segment=1.0, max_segment=4.0)
        for i in range(1, len(result)):
            gap = result[i].timestamp - result[i - 1].timestamp
            assert gap <= 4.0 + 0.01, (
                f"Gap {gap:.3f}s between cuts at {result[i-1].timestamp:.3f} "
                f"and {result[i].timestamp:.3f} exceeds max_segment 4.0"
            )

    def test_max_segment_enforced_end_to_end(self):
        """Comprehensive regression: realistic beats, verify no gap > max_segment anywhere."""
        # Simulate ~143 BPM, 60s of music
        beats = _make_beats(144, interval=0.42)
        sections = [
            MusicSection("intro", 0.0, 15.0, 0.2),
            MusicSection("verse", 15.0, 30.0, 0.4),
            MusicSection("chorus", 30.0, 45.0, 0.8),
            MusicSection("outro", 45.0, 60.5, 0.2),
        ]
        max_seg = 6.0
        result = select_cut_points(beats, sections, 143.0, min_segment=1.0, max_segment=max_seg)
        for i in range(1, len(result)):
            gap = result[i].timestamp - result[i - 1].timestamp
            assert gap <= max_seg + 0.01, (
                f"Gap {gap:.3f}s between cuts at {result[i-1].timestamp:.3f} "
                f"and {result[i].timestamp:.3f} exceeds max_segment {max_seg}"
            )

    def test_ensures_final_beat(self):
        beats = _make_beats(10, interval=1.0)  # 0-9s
        sections = [MusicSection("verse", 0.0, 5.0, 0.5)]  # only covers first half
        result = select_cut_points(beats, sections, 120.0, 0.25, 8.0)
        # Should have the last beat
        assert result[-1].timestamp == beats[-1].timestamp

    def test_section_boundary_swap_preserves_new_section_beat(self):
        """When a new section's first beat conflicts with the previous section's
        last cut, the new section's beat should replace it (swap), not be dropped."""
        # Short section with low density — only 1 beat selected
        beats = [
            BeatInfo(timestamp=0.0, strength=0.8, is_downbeat=True),
            BeatInfo(timestamp=1.0, strength=0.5, is_downbeat=False),
            BeatInfo(timestamp=2.0, strength=0.8, is_downbeat=True),
            # Second section starts here — first beat close to last cut of section 1
            BeatInfo(timestamp=2.3, strength=0.8, is_downbeat=True),
            BeatInfo(timestamp=3.0, strength=0.5, is_downbeat=False),
            BeatInfo(timestamp=4.0, strength=0.5, is_downbeat=False),
        ]
        sections = [
            MusicSection("intro", 0.0, 2.2, 0.8),
            MusicSection("verse", 2.2, 5.0, 0.8),
        ]
        result = select_cut_points(beats, sections, 120.0, min_segment=0.5, max_segment=8.0)
        timestamps = [b.timestamp for b in result]
        # The new section's first beat at 2.3 should be present (swapped in)
        assert 2.3 in timestamps


class TestTransitionCuts:
    def test_transition_forces_cut_in_long_gap(self):
        """An energy transition within a long gap should force a cut point."""
        beats = _make_beats(20, interval=0.5)  # 0-10s
        sections = [MusicSection("verse", 0.0, 10.0, 0.1)]  # low energy = few cuts
        # Without transitions
        base_cuts = select_cut_points(beats, sections, 120.0, 1.0, 8.0)

        # Add a transition at t=5.0
        transitions = [EnergyTransition(timestamp=5.0, magnitude=0.5, direction="up")]
        cuts_with_transition = select_cut_points(
            beats, sections, 120.0, 1.0, 8.0, energy_transitions=transitions
        )

        # Should have at least one more cut near t=5.0
        near_5 = [c for c in cuts_with_transition if 4.0 <= c.timestamp <= 6.0]
        assert len(near_5) >= 1
        assert len(cuts_with_transition) >= len(base_cuts)

    def test_transition_respects_min_segment(self):
        """Transition cut should not be inserted if it would violate min_segment."""
        beats = _make_beats(10, interval=0.5)
        sections = [MusicSection("verse", 0.0, 5.0, 0.9)]  # high energy = dense cuts
        transitions = [EnergyTransition(timestamp=1.0, magnitude=0.5, direction="up")]
        cuts = select_cut_points(
            beats, sections, 120.0, 1.0, 8.0, energy_transitions=transitions
        )
        for i in range(1, len(cuts)):
            gap = cuts[i].timestamp - cuts[i - 1].timestamp
            assert gap >= 1.0 - 0.01

    def test_no_transitions_backward_compatible(self):
        """Passing no transitions should produce identical results."""
        beats = _make_beats(20, interval=0.5)
        sections = [MusicSection("verse", 0.0, 10.0, 0.5)]
        cuts_none = select_cut_points(beats, sections, 120.0, 1.0, 8.0, energy_transitions=None)
        cuts_empty = select_cut_points(beats, sections, 120.0, 1.0, 8.0, energy_transitions=[])
        assert [c.timestamp for c in cuts_none] == [c.timestamp for c in cuts_empty]

    def test_transition_outside_range_ignored(self):
        """Transitions outside the cut point range should be ignored."""
        beats = _make_beats(10, interval=0.5)
        sections = [MusicSection("verse", 0.0, 5.0, 0.5)]
        transitions = [EnergyTransition(timestamp=100.0, magnitude=0.8, direction="up")]
        cuts_with = select_cut_points(
            beats, sections, 120.0, 1.0, 8.0, energy_transitions=transitions
        )
        cuts_without = select_cut_points(beats, sections, 120.0, 1.0, 8.0)
        assert [c.timestamp for c in cuts_with] == [c.timestamp for c in cuts_without]

    def test_multiple_transitions_insert_multiple_cuts(self):
        """Multiple well-spaced transitions should each get a cut point."""
        beats = _make_beats(40, interval=0.5)  # 0-20s
        sections = [MusicSection("verse", 0.0, 20.0, 0.05)]  # very low energy
        base_cuts = select_cut_points(beats, sections, 120.0, 1.0, 8.0)

        transitions = [
            EnergyTransition(timestamp=5.0, magnitude=0.5, direction="up"),
            EnergyTransition(timestamp=12.0, magnitude=0.6, direction="down"),
        ]
        cuts_with = select_cut_points(
            beats, sections, 120.0, 1.0, 8.0, energy_transitions=transitions
        )
        assert len(cuts_with) >= len(base_cuts) + 1
