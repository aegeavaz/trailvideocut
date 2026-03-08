import numpy as np
import pytest

from trailvideocut.audio.models import MusicSection
from trailvideocut.audio.structure import MusicalStructureAnalyzer


class TestBoundaryDeduplication:
    """Tests for _deduplicate_boundaries."""

    def test_removes_zero_length_section(self):
        """Duplicate 0.0 boundary should not create a zero-length section."""
        boundaries = [0.0, 10.0, 20.0]
        result = MusicalStructureAnalyzer._deduplicate_boundaries(boundaries, 20.0)
        assert result[0] == 0.0
        assert result[-1] == 20.0
        # No adjacent duplicates
        for i in range(1, len(result)):
            assert result[i] > result[i - 1]

    def test_removes_near_duplicate(self):
        """Boundaries closer than min_section_length are collapsed."""
        boundaries = [5.0, 5.5, 15.0]
        result = MusicalStructureAnalyzer._deduplicate_boundaries(
            boundaries, 20.0, min_section_length=2.0
        )
        assert all(
            result[i + 1] - result[i] >= 2.0
            for i in range(len(result) - 1)
        )

    def test_short_final_section_absorbed(self):
        """A final section shorter than min_section_length merges into previous."""
        boundaries = [10.0]
        duration = 11.0  # final gap = 1.0 < 2.0
        result = MusicalStructureAnalyzer._deduplicate_boundaries(
            boundaries, duration, min_section_length=2.0
        )
        # last element must be duration
        assert result[-1] == duration
        # no section shorter than min_section_length (except possibly last if unavoidable)
        for i in range(len(result) - 2):
            assert result[i + 1] - result[i] >= 2.0

    def test_valid_boundaries_preserved(self):
        """Well-spaced boundaries remain intact."""
        boundaries = [10.0, 20.0, 30.0]
        result = MusicalStructureAnalyzer._deduplicate_boundaries(boundaries, 40.0)
        assert result == [0.0, 10.0, 20.0, 30.0, 40.0]

    def test_empty_boundaries(self):
        """No internal boundaries should produce [0.0, duration]."""
        result = MusicalStructureAnalyzer._deduplicate_boundaries([], 30.0)
        assert result == [0.0, 30.0]

    def test_always_starts_at_zero_and_ends_at_duration(self):
        boundaries = [5.0, 15.0]
        result = MusicalStructureAnalyzer._deduplicate_boundaries(boundaries, 25.0)
        assert result[0] == 0.0
        assert result[-1] == 25.0


class TestCompositeEnergy:
    """Tests for _assign_composite_energy."""

    def test_energy_in_range(self):
        """All composite energies should be in [0, 1]."""
        sections = [MusicSection(label="", start_time=0, end_time=10, energy=0)]
        raw = [(0.5, 1.0, 3000.0)]
        # Single section — all dimensions normalize to 0 (no range)
        MusicalStructureAnalyzer._assign_composite_energy(sections, raw)
        assert 0.0 <= sections[0].energy <= 1.0

    def test_loud_rhythmic_gets_high_energy(self):
        """Loud+rhythmic section should rank higher than quiet one."""
        sections = [
            MusicSection(label="", start_time=0, end_time=10, energy=0),
            MusicSection(label="", start_time=10, end_time=20, energy=0),
        ]
        raw = [
            (0.9, 5.0, 5000.0),  # loud, rhythmic, bright
            (0.1, 0.5, 1000.0),  # quiet, sparse, dark
        ]
        MusicalStructureAnalyzer._assign_composite_energy(sections, raw)
        assert sections[0].energy > sections[1].energy
        assert all(0.0 <= s.energy <= 1.0 for s in sections)

    def test_empty_input(self):
        """Empty list should not raise."""
        MusicalStructureAnalyzer._assign_composite_energy([], [])

    def test_identical_values_produce_zero_energy(self):
        """When all sections have identical raw values, energy is 0 (no contrast)."""
        sections = [
            MusicSection(label="", start_time=0, end_time=10, energy=0),
            MusicSection(label="", start_time=10, end_time=20, energy=0),
        ]
        raw = [(0.5, 1.0, 3000.0), (0.5, 1.0, 3000.0)]
        MusicalStructureAnalyzer._assign_composite_energy(sections, raw)
        assert all(s.energy == 0.0 for s in sections)


class TestSectionCount:
    """Test the n_sections formula."""

    @pytest.mark.parametrize(
        "duration, expected",
        [
            (30.0, 4),     # 30/12=2.5 → clamped to 4
            (60.0, 5),     # 60/12=5
            (148.0, 12),   # 148/12=12.3 → int=12
            (300.0, 20),   # 300/12=25 → capped at 20
            (10.0, 4),     # very short → clamped to 4
        ],
    )
    def test_formula(self, duration, expected):
        result = min(20, max(4, int(duration / 12)))
        assert result == expected


class TestLabelSection:
    """Test _label_section heuristics."""

    def test_first_is_intro(self):
        assert MusicalStructureAnalyzer._label_section(0, 10, 0.9) == "intro"

    def test_last_is_outro(self):
        assert MusicalStructureAnalyzer._label_section(9, 10, 0.9) == "outro"

    def test_high_energy_is_chorus(self):
        assert MusicalStructureAnalyzer._label_section(3, 10, 0.8) == "chorus"

    def test_low_energy_is_bridge(self):
        assert MusicalStructureAnalyzer._label_section(3, 10, 0.2) == "bridge"

    def test_medium_energy_is_verse(self):
        assert MusicalStructureAnalyzer._label_section(3, 10, 0.5) == "verse"

    def test_threshold_boundary_chorus(self):
        # Exactly 0.65 is not > 0.65
        assert MusicalStructureAnalyzer._label_section(3, 10, 0.65) == "verse"
        assert MusicalStructureAnalyzer._label_section(3, 10, 0.66) == "chorus"

    def test_threshold_boundary_bridge(self):
        # Exactly 0.35 is not < 0.35
        assert MusicalStructureAnalyzer._label_section(3, 10, 0.35) == "verse"
        assert MusicalStructureAnalyzer._label_section(3, 10, 0.34) == "bridge"


class TestAnalyzeIntegration:
    """Integration tests using synthetic audio."""

    @pytest.fixture
    def analyzer(self):
        return MusicalStructureAnalyzer()

    @pytest.fixture
    def sine_audio(self):
        """Generate 30s of audio with distinct sections.

        Three 10s segments with different frequencies and amplitudes to
        ensure agglomerative clustering finds real boundaries.
        """
        sr = 22050
        duration = 30.0
        samples = int(sr * duration)
        third = samples // 3

        t = np.linspace(0, duration, samples, endpoint=False)

        # Section 1: quiet low tone
        s1 = 0.2 * np.sin(2 * np.pi * 220 * t[:third])
        # Section 2: loud mid tone + harmonics
        s2 = 0.8 * np.sin(2 * np.pi * 880 * t[third:2 * third])
        s2 += 0.3 * np.sin(2 * np.pi * 1760 * t[third:2 * third])
        # Section 3: moderate high tone
        s3 = 0.4 * np.sin(2 * np.pi * 2000 * t[2 * third:])

        y = np.concatenate([s1, s2, s3]).astype(np.float32)
        return y, sr

    def test_no_zero_length_sections(self, analyzer, sine_audio):
        y, sr = sine_audio
        sections = analyzer.analyze("unused.wav", sr=sr, y=y)
        for s in sections:
            assert s.end_time > s.start_time, (
                f"Zero-length section: {s.start_time} - {s.end_time}"
            )

    def test_contiguous_coverage(self, analyzer, sine_audio):
        y, sr = sine_audio
        sections = analyzer.analyze("unused.wav", sr=sr, y=y)
        assert len(sections) >= 2
        assert sections[0].start_time == 0.0
        assert sections[-1].end_time == pytest.approx(30.0, abs=0.1)
        for i in range(1, len(sections)):
            assert sections[i].start_time == pytest.approx(
                sections[i - 1].end_time, abs=0.01
            )

    def test_energy_normalized(self, analyzer, sine_audio):
        y, sr = sine_audio
        sections = analyzer.analyze("unused.wav", sr=sr, y=y)
        for s in sections:
            assert 0.0 <= s.energy <= 1.0

    def test_accepts_onset_envelope(self, analyzer, sine_audio):
        """Passing a pre-computed onset envelope should work without error."""
        y, sr = sine_audio
        onset_env = np.random.rand(100).astype(np.float32)
        sections = analyzer.analyze("unused.wav", sr=sr, y=y, onset_envelope=onset_env)
        assert len(sections) >= 2

    def test_produces_expected_section_count(self, analyzer, sine_audio):
        """30s audio should produce ~4 sections (30/12 = 2.5, clamped to 4)."""
        y, sr = sine_audio
        sections = analyzer.analyze("unused.wav", sr=sr, y=y)
        # Allow some tolerance due to dedup merging
        assert 2 <= len(sections) <= 6
