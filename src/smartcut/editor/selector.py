import bisect

from smartcut.audio.models import AudioAnalysis, BeatInfo
from smartcut.config import SmartCutConfig
from smartcut.editor.models import CutPlan, EditDecision
from smartcut.video.models import VideoSegment


class SegmentSelector:
    """Select video segments using zone-based chronological selection.

    The video timeline is divided into N proportional zones (one per beat interval).
    Within each zone, the highest-scoring segment is selected.
    This guarantees: chronological order, no reuse, and visual interest.
    """

    def __init__(self, config: SmartCutConfig):
        self.config = config

    def select(self, audio: AudioAnalysis, segments: list[VideoSegment]) -> CutPlan:
        """Produce a CutPlan by dividing the video into zones aligned to beat intervals."""
        beats = audio.beats
        if len(beats) < 2:
            raise ValueError("Need at least 2 beats to create a cut plan")
        if not segments:
            raise ValueError("No video segments available")

        # Build beat intervals
        intervals = [
            (beats[i], beats[i + 1]) for i in range(len(beats) - 1)
        ]

        # Compute video duration from segments
        video_duration = segments[-1].end_time

        # Pre-sort segments by midpoint and extract midpoints/start_times for binary search
        sorted_segments = sorted(segments, key=lambda s: s.midpoint)
        midpoints = [s.midpoint for s in sorted_segments]
        start_times = [s.start_time for s in sorted_segments]

        # Compute proportional zones
        zones = self._compute_zones(intervals, video_duration)

        # Resolve must-include timestamps to zones
        include_map, include_anchors = self._resolve_includes(
            zones, sorted_segments, midpoints, start_times
        )

        # For each zone, pick the best segment
        decisions: list[EditDecision] = []
        for idx, (zone_start, zone_end, beat_start, beat_end) in enumerate(zones):
            needed_duration = beat_end.timestamp - beat_start.timestamp

            # Check if this zone has a forced include
            if idx in include_map:
                best = include_map[idx]
            else:
                best = self._pick_best_in_zone(
                    sorted_segments, midpoints, zone_start, zone_end
                )

            if best is None:
                # No candidate in zone — find nearest segment
                best = self._nearest_segment(
                    sorted_segments, midpoints, (zone_start + zone_end) / 2
                )

            anchor = include_anchors.get(idx)
            source_start, source_end = self._align_segment(best, needed_duration, anchor)

            decisions.append(
                EditDecision(
                    beat_index=idx,
                    source_start=source_start,
                    source_end=source_end,
                    target_start=beat_start.timestamp,
                    target_end=beat_end.timestamp,
                    interest_score=best.interest.composite,
                )
            )

        # Merge consecutive decisions with adjacent source positions
        merged = self._merge_continuous(decisions)

        return CutPlan(
            decisions=merged,
            total_duration=audio.duration,
            song_tempo=audio.tempo,
            transition_style=self.config.transition_style.value,
            crossfade_duration=self.config.crossfade_duration,
            zones_analyzed=len(decisions),
        )

    def _compute_zones(
        self,
        intervals: list[tuple[BeatInfo, BeatInfo]],
        video_duration: float,
    ) -> list[tuple[float, float, BeatInfo, BeatInfo]]:
        """Divide the video timeline into N proportional zones.

        Each zone's duration is proportional to its beat interval's share
        of the total song duration. Returns (zone_start, zone_end, beat_start, beat_end).
        """
        total_beat_time = sum(
            b2.timestamp - b1.timestamp for b1, b2 in intervals
        )
        if total_beat_time <= 0:
            total_beat_time = 1.0

        zones = []
        video_cursor = 0.0
        for beat_start, beat_end in intervals:
            beat_dur = beat_end.timestamp - beat_start.timestamp
            zone_dur = (beat_dur / total_beat_time) * video_duration
            zone_end = min(video_cursor + zone_dur, video_duration)
            zones.append((video_cursor, zone_end, beat_start, beat_end))
            video_cursor = zone_end

        return zones

    def _pick_best_in_zone(
        self,
        sorted_segments: list[VideoSegment],
        midpoints: list[float],
        zone_start: float,
        zone_end: float,
    ) -> VideoSegment | None:
        """Pick the segment with the highest composite score whose midpoint falls in the zone.

        Uses binary search on pre-sorted midpoints for O(log N) lookup.
        """
        lo = bisect.bisect_left(midpoints, zone_start)
        hi = bisect.bisect_left(midpoints, zone_end)
        if lo >= hi:
            return None
        return max(sorted_segments[lo:hi], key=lambda s: s.interest.composite)

    def _nearest_segment(
        self,
        sorted_segments: list[VideoSegment],
        midpoints: list[float],
        target_time: float,
    ) -> VideoSegment:
        """Find the segment whose midpoint is closest to target_time using binary search."""
        pos = bisect.bisect_left(midpoints, target_time)
        candidates = []
        if pos < len(sorted_segments):
            candidates.append(sorted_segments[pos])
        if pos > 0:
            candidates.append(sorted_segments[pos - 1])
        return min(candidates, key=lambda s: abs(s.midpoint - target_time))

    def _resolve_includes(
        self,
        zones: list[tuple[float, float, BeatInfo, BeatInfo]],
        sorted_segments: list[VideoSegment],
        midpoints: list[float],
        start_times: list[float],
    ) -> tuple[dict[int, VideoSegment], dict[int, float]]:
        """Map user-specified must-include timestamps to their zone's segment.

        Returns (include_map, include_anchors) where anchors map zone index
        to the timestamp that must be contained in the extracted clip.
        """
        include_map: dict[int, VideoSegment] = {}
        include_anchors: dict[int, float] = {}
        for ts in self.config.include_timestamps:
            # Find which zone contains this timestamp
            for idx, (zone_start, zone_end, _, _) in enumerate(zones):
                if zone_start <= ts < zone_end:
                    seg = self._find_segment_at(sorted_segments, midpoints, ts)
                    if seg is not None:
                        include_map[idx] = seg
                        include_anchors[idx] = ts
                    break
        return include_map, include_anchors

    def _find_segment_at(
        self,
        sorted_segments: list[VideoSegment],
        midpoints: list[float],
        timestamp: float,
    ) -> VideoSegment | None:
        """Find the segment that contains the given timestamp using binary search."""
        # Find segments near this timestamp by midpoint proximity
        pos = bisect.bisect_left(midpoints, timestamp)

        # Check neighbors around the insertion point for containment
        best = None
        for i in range(max(0, pos - 5), min(len(sorted_segments), pos + 5)):
            seg = sorted_segments[i]
            if seg.start_time <= timestamp <= seg.end_time:
                best = seg
                break

        if best is not None:
            return best

        # Fallback: nearest by midpoint
        if sorted_segments:
            return self._nearest_segment(sorted_segments, midpoints, timestamp)
        return None

    def _align_segment(
        self,
        segment: VideoSegment,
        needed_duration: float,
        anchor: float | None = None,
    ) -> tuple[float, float]:
        """Extract exactly needed_duration from the segment.

        If anchor is provided, center the extraction around that timestamp
        (ensuring the anchor is contained). Otherwise, center within the segment.
        """
        available = segment.duration
        if needed_duration >= available:
            return segment.start_time, segment.end_time

        if anchor is not None:
            # Center around the anchor timestamp
            start = anchor - needed_duration / 2
            end = anchor + needed_duration / 2
            # Clamp to segment boundaries
            if start < segment.start_time:
                start = segment.start_time
                end = start + needed_duration
            if end > segment.end_time:
                end = segment.end_time
                start = end - needed_duration
            return max(start, segment.start_time), min(end, segment.end_time)

        # Default: center within the segment
        excess = available - needed_duration
        start = segment.start_time + excess / 2
        end = start + needed_duration
        return start, end

    def _merge_continuous(self, decisions: list[EditDecision]) -> list[EditDecision]:
        """Merge consecutive decisions whose source positions are adjacent.

        Consecutive zone decisions that pick from nearby source positions
        (gap < segment_window) get merged into a single longer clip.
        This eliminates unnecessary cuts within continuous stretches of video.
        """
        if len(decisions) <= 1:
            return decisions

        threshold = self.config.segment_window
        merged: list[EditDecision] = []
        group_start = decisions[0]
        group_target_end = decisions[0].target_end

        for i in range(1, len(decisions)):
            prev = decisions[i - 1]
            curr = decisions[i]
            gap = curr.source_start - prev.source_end

            if gap < threshold:
                # Adjacent — extend current group
                group_target_end = curr.target_end
            else:
                # Scene change — finalize current group, start new one
                total_dur = group_target_end - group_start.target_start
                merged.append(EditDecision(
                    beat_index=group_start.beat_index,
                    source_start=group_start.source_start,
                    source_end=group_start.source_start + total_dur,
                    target_start=group_start.target_start,
                    target_end=group_target_end,
                    interest_score=group_start.interest_score,
                ))
                group_start = curr
                group_target_end = curr.target_end

        # Finalize last group
        total_dur = group_target_end - group_start.target_start
        merged.append(EditDecision(
            beat_index=group_start.beat_index,
            source_start=group_start.source_start,
            source_end=group_start.source_start + total_dur,
            target_start=group_start.target_start,
            target_end=group_target_end,
            interest_score=group_start.interest_score,
        ))
        return merged
