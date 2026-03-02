import numpy as np

from smartcut.audio.models import AudioAnalysis, BeatInfo
from smartcut.config import SegmentPreference, SmartCutConfig
from smartcut.editor.models import CutPlan, EditDecision
from smartcut.video.models import VideoSegment


class SegmentSelector:
    """Select the best video segments to match beat intervals."""

    def __init__(self, config: SmartCutConfig):
        self.config = config

    def select(self, audio: AudioAnalysis, segments: list[VideoSegment]) -> CutPlan:
        """Given beats and scored video segments, produce a CutPlan."""
        beats = audio.beats
        if len(beats) < 2:
            raise ValueError("Need at least 2 beats to create a cut plan")

        # Build beat intervals
        intervals = []
        for i in range(len(beats) - 1):
            intervals.append((beats[i], beats[i + 1], beats[i + 1].timestamp - beats[i].timestamp))

        # Pre-assign must-include timestamps
        reserved = self._reserve_includes(intervals, segments)

        # Select segments for each interval
        decisions: list[EditDecision] = []
        used_midpoints: list[float] = []

        for idx, (beat_start, beat_end, needed_duration) in enumerate(intervals):
            # Check if this interval has a reserved segment
            if idx in reserved:
                best_segment = reserved[idx]
            else:
                best_segment = self._find_best_segment(
                    segments, needed_duration, used_midpoints, beat_start
                )

            if best_segment is None:
                best_segment = self._fallback_segment(segments, needed_duration, used_midpoints)

            source_start, source_end = self._align_segment(best_segment, needed_duration)

            decisions.append(
                EditDecision(
                    beat_index=idx,
                    source_start=source_start,
                    source_end=source_end,
                    target_start=beat_start.timestamp,
                    target_end=beat_end.timestamp,
                    interest_score=best_segment.interest.composite,
                )
            )
            used_midpoints.append(best_segment.midpoint)

        return CutPlan(
            decisions=decisions,
            total_duration=beats[-1].timestamp - beats[0].timestamp,
            song_tempo=audio.tempo,
            transition_style=self.config.transition_style.value,
            crossfade_duration=self.config.crossfade_duration,
        )

    def _reserve_includes(
        self,
        intervals: list[tuple[BeatInfo, BeatInfo, float]],
        segments: list[VideoSegment],
    ) -> dict[int, VideoSegment]:
        """Pre-assign user-specified must-include timestamps to their nearest beat intervals."""
        reserved: dict[int, VideoSegment] = {}
        for ts in self.config.include_timestamps:
            # Find the segment containing this timestamp
            seg = self._find_segment_at(segments, ts)
            if seg is None:
                continue
            # Find the nearest beat interval
            best_idx = 0
            best_dist = float("inf")
            for idx, (beat_start, beat_end, _) in enumerate(intervals):
                mid = (beat_start.timestamp + beat_end.timestamp) / 2
                dist = abs(ts - mid)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            reserved[best_idx] = seg
        return reserved

    def _find_segment_at(self, segments: list[VideoSegment], timestamp: float) -> VideoSegment | None:
        """Find the segment that contains the given timestamp."""
        for seg in segments:
            if seg.start_time <= timestamp <= seg.end_time:
                return seg
        # If exact match not found, find nearest
        if segments:
            return min(segments, key=lambda s: abs(s.midpoint - timestamp))
        return None

    def _find_best_segment(
        self,
        segments: list[VideoSegment],
        needed_duration: float,
        used_midpoints: list[float],
        beat_start: BeatInfo,
    ) -> VideoSegment | None:
        """Score each candidate segment for this beat interval and return the best."""
        candidates: list[tuple[VideoSegment, float]] = []

        for seg in segments:
            if seg.duration < needed_duration * 0.5:
                continue

            interest = seg.interest.composite
            diversity = self._diversity_score(seg.midpoint, used_midpoints)
            transition_bonus = 0.1 if seg.scene_boundary_near else 0.0
            energy_match = beat_start.strength * interest

            if self.config.segment_preference == SegmentPreference.BALANCED:
                score = (
                    interest * 0.4
                    + diversity * self.config.diversity_weight
                    + energy_match * 0.2
                    + transition_bonus
                )
            elif self.config.segment_preference == SegmentPreference.HIGH_ACTION:
                score = interest * 0.8 + energy_match * 0.2
            else:  # CHRONOLOGICAL
                chrono = self._chronological_score(seg, used_midpoints)
                score = interest * 0.3 + chrono * 0.5 + diversity * 0.2

            candidates.append((seg, score))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def _diversity_score(self, midpoint: float, used_midpoints: list[float]) -> float:
        """Score 0-1 where 1 = maximally distant from all used segments."""
        if not used_midpoints:
            return 1.0
        min_dist = min(abs(midpoint - u) for u in used_midpoints)
        return min(1.0, min_dist / 60.0)

    def _chronological_score(self, seg: VideoSegment, used_midpoints: list[float]) -> float:
        """Score how well this segment follows chronologically from the last used one."""
        if not used_midpoints:
            return 1.0
        last = used_midpoints[-1]
        if seg.midpoint > last:
            return min(1.0, 1.0 / (1.0 + abs(seg.midpoint - last - 10.0)))
        return 0.0

    def _align_segment(
        self, segment: VideoSegment, needed_duration: float
    ) -> tuple[float, float]:
        """Extract exactly needed_duration centered within the segment."""
        available = segment.duration
        if needed_duration >= available:
            return segment.start_time, segment.end_time
        excess = available - needed_duration
        start = segment.start_time + excess / 2
        end = start + needed_duration
        return start, end

    def _fallback_segment(
        self,
        segments: list[VideoSegment],
        needed_duration: float,
        used_midpoints: list[float],
    ) -> VideoSegment:
        """Pick the best unused segment when no ideal candidate was found."""
        # Sort by composite interest descending
        sorted_segs = sorted(segments, key=lambda s: s.interest.composite, reverse=True)
        for seg in sorted_segs:
            if seg.duration >= needed_duration * 0.3:
                return seg
        return sorted_segs[0]
