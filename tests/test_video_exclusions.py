"""Unit tests for the exclusion-range data model and validation helpers."""

from __future__ import annotations

import pytest

from trailvideocut.video.exclusions import (
    ExclusionRange,
    contains,
    overlaps,
    validate_exclusions,
)


class TestExclusionRangeConstruction:
    def test_valid_range_accepted(self):
        r = ExclusionRange(start=1.0, end=2.5)
        assert r.start == 1.0
        assert r.end == 2.5

    def test_inverted_rejected(self):
        with pytest.raises(ValueError, match="start < end"):
            ExclusionRange(start=5.0, end=3.0)

    def test_zero_length_rejected(self):
        with pytest.raises(ValueError, match="start < end"):
            ExclusionRange(start=4.0, end=4.0)

    def test_ints_coerced_to_float(self):
        r = ExclusionRange(start=1, end=3)
        assert isinstance(r.start, float)
        assert isinstance(r.end, float)


class TestOverlaps:
    def test_clear_overlap(self):
        assert overlaps(ExclusionRange(0, 10), ExclusionRange(5, 15))

    def test_one_inside_other(self):
        assert overlaps(ExclusionRange(0, 10), ExclusionRange(2, 5))

    def test_touching_endpoints_not_overlap(self):
        assert not overlaps(ExclusionRange(0, 10), ExclusionRange(10, 20))
        assert not overlaps(ExclusionRange(10, 20), ExclusionRange(0, 10))

    def test_disjoint(self):
        assert not overlaps(ExclusionRange(0, 5), ExclusionRange(10, 15))

    def test_symmetric(self):
        a = ExclusionRange(0, 10)
        b = ExclusionRange(5, 15)
        assert overlaps(a, b) == overlaps(b, a)


class TestContains:
    def test_strictly_inside(self):
        ranges = [ExclusionRange(10, 20)]
        assert contains(ranges, 15.0)

    def test_boundary_not_contained(self):
        ranges = [ExclusionRange(10, 20)]
        assert not contains(ranges, 10.0)
        assert not contains(ranges, 20.0)

    def test_outside(self):
        ranges = [ExclusionRange(10, 20)]
        assert not contains(ranges, 5.0)
        assert not contains(ranges, 25.0)

    def test_empty_ranges(self):
        assert not contains([], 1.0)

    def test_contained_in_any(self):
        ranges = [ExclusionRange(0, 5), ExclusionRange(10, 20)]
        assert contains(ranges, 15.0)
        assert not contains(ranges, 7.0)


class TestValidateExclusions:
    def test_empty_list_ok(self):
        validate_exclusions([], video_duration=100.0, include_timestamps=[])

    def test_valid_list_ok(self):
        ranges = [ExclusionRange(0, 10), ExclusionRange(20, 30)]
        validate_exclusions(ranges, video_duration=100.0, include_timestamps=[15.0])

    def test_touching_endpoints_ok(self):
        ranges = [ExclusionRange(10, 20), ExclusionRange(20, 30)]
        validate_exclusions(ranges, video_duration=100.0, include_timestamps=[])

    def test_negative_start_rejected(self):
        r = ExclusionRange(1, 5)
        object.__setattr__(r, "start", -1.0)
        with pytest.raises(ValueError, match="outside video duration"):
            validate_exclusions([r], video_duration=100.0, include_timestamps=[])

    def test_end_beyond_duration_rejected(self):
        ranges = [ExclusionRange(50, 200)]
        with pytest.raises(ValueError, match="outside video duration"):
            validate_exclusions(ranges, video_duration=100.0, include_timestamps=[])

    def test_overlap_rejected(self):
        ranges = [ExclusionRange(0, 20), ExclusionRange(10, 30)]
        with pytest.raises(ValueError, match="overlap"):
            validate_exclusions(ranges, video_duration=100.0, include_timestamps=[])

    def test_include_inside_range_rejected(self):
        ranges = [ExclusionRange(10, 20)]
        with pytest.raises(ValueError, match="15"):
            validate_exclusions(ranges, video_duration=100.0, include_timestamps=[15.0])

    def test_include_on_boundary_accepted(self):
        ranges = [ExclusionRange(10, 20)]
        validate_exclusions(
            ranges, video_duration=100.0, include_timestamps=[10.0, 20.0]
        )

    def test_inverted_via_mutation_rejected(self):
        r = ExclusionRange(1, 5)
        object.__setattr__(r, "end", 0.5)
        with pytest.raises(ValueError, match="inverted"):
            validate_exclusions([r], video_duration=100.0, include_timestamps=[])
