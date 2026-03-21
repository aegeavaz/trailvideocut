import bisect
import statistics

from trailvideocut.audio.models import AudioAnalysis, BeatInfo, MusicSection
from trailvideocut.config import TrailVideoCutConfig
from trailvideocut.editor.models import CutPlan, EditDecision
from trailvideocut.video.models import VideoSegment


class SegmentSelector:
    """Select video segments using coverage-zone + greedy selection.

    Video is divided into K coverage zones to guarantee temporal spread,
    then remaining slots are filled greedily by score with overlap prevention.
    Quality-adaptive cut count reduces clips when footage is uniform.
    """

    def __init__(self, config: TrailVideoCutConfig):
        self.config = config

    def select(
        self,
        audio: AudioAnalysis,
        segments: list[VideoSegment],
        cut_points: list[BeatInfo] | None = None,
    ) -> CutPlan:
        """Produce a CutPlan using global score-ranked selection."""
        beats = cut_points if cut_points is not None else audio.beats
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

        # Compute global energy for energy-weighted scoring
        global_energy = self._compute_global_energy(audio.sections, video_duration)

        # Quality-adaptive cut count: reduce N if footage is uniform
        n_intervals = len(intervals)
        scores = [s.interest.energy_weighted_composite(
            self._energy_at(s.midpoint, audio.sections)
        ) for s in segments]
        score_cv = self._coefficient_of_variation(scores)

        target_clips = n_intervals
        merged_intervals = list(intervals)
        if score_cv < self.config.quality_cv_threshold and n_intervals > 2:
            # Reduce proportionally: lower CV -> more reduction
            reduction_ratio = 1.0 - (score_cv / self.config.quality_cv_threshold)
            reduction_fraction = reduction_ratio * self.config.quality_max_reduction
            n_to_remove = int(n_intervals * reduction_fraction)
            target_clips = max(2, n_intervals - n_to_remove)
            merged_intervals = self._merge_low_energy_intervals(
                intervals, audio.sections, target_clips
            )
            # Merging may stop early due to max_segment_duration cap;
            # use actual merged count so selected length matches.
            target_clips = len(merged_intervals)

        # Pre-sort segments by midpoint for binary search
        sorted_segments = sorted(segments, key=lambda s: s.midpoint)
        midpoints = [s.midpoint for s in sorted_segments]

        # Resolve must-include timestamps
        include_segments, include_anchors = self._resolve_include_segments(
            sorted_segments, midpoints
        )

        # Global score-ranked selection
        selected = self._select_top_segments(
            sorted_segments, midpoints, audio.sections,
            target_clips, video_duration, include_segments
        )

        # Build edit decisions from selected segments mapped to intervals
        decisions: list[EditDecision] = []
        for idx, (beat_start, beat_end) in enumerate(merged_intervals):
            needed_duration = beat_end.timestamp - beat_start.timestamp
            seg = selected[idx]

            # Check if this segment has an include anchor
            anchor = None
            for inc_seg, inc_ts in zip(include_segments, include_anchors):
                if seg is inc_seg:
                    anchor = inc_ts
                    break

            source_start, source_end = self._align_segment(seg, needed_duration, anchor)

            decisions.append(
                EditDecision(
                    beat_index=idx,
                    source_start=source_start,
                    source_end=source_end,
                    target_start=beat_start.timestamp,
                    target_end=beat_end.timestamp,
                    interest_score=seg.interest.energy_weighted_composite(
                        self._energy_at(seg.midpoint, audio.sections)
                    ),
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
            clips_selected=len(decisions),
            score_cv=score_cv,
        )

    def _select_top_segments(
        self,
        sorted_segments: list[VideoSegment],
        midpoints: list[float],
        sections: list[MusicSection],
        n: int,
        video_duration: float,
        include_segments: list[VideoSegment],
    ) -> list[VideoSegment]:
        """Select top-N segments using coverage zones + greedy fill.

        1. Divide video into K coverage zones, pick best segment per zone
        2. Greedily fill remaining slots by score with overlap prevention
        3. Sort chronologically and return
        """
        min_spacing = self.config.segment_window / 2  # overlap prevention only

        # Cluster density limit: prevent too many segments from one source region
        cluster_range = self.config.segment_window * 2
        avg_interval = video_duration / n if n > 0 else video_duration
        max_from_region = max(1, int(self.config.max_segment_duration / avg_interval))

        def score_func(s: VideoSegment) -> float:
            return s.interest.energy_weighted_composite(
                self._energy_at(s.midpoint, sections)
            )

        # Step 1: Coverage zones — reserve 1 best segment per zone
        free_slots = max(1, n - len(include_segments))
        coverage_zone_count = min(max(4, n // 8), free_slots)
        zone_size = video_duration / coverage_zone_count

        include_set = set(id(s) for s in include_segments)
        coverage_picks: list[VideoSegment] = []
        for zone_idx in range(coverage_zone_count):
            zone_start = zone_idx * zone_size
            zone_end = (zone_idx + 1) * zone_size
            candidates = [
                s for s in sorted_segments
                if zone_start <= s.midpoint < zone_end
                and id(s) not in include_set
            ]
            if candidates:
                best = max(candidates, key=score_func)
                coverage_picks.append(best)

        # Step 2: Build initial selected list
        selected: list[VideoSegment] = list(include_segments)
        selected_midpoints: list[float] = sorted([s.midpoint for s in selected])

        for seg in coverage_picks:
            if id(seg) not in {id(s) for s in selected}:
                if (self._respects_spacing(seg.midpoint, selected_midpoints, min_spacing)
                        and self._within_cluster_limit(seg.midpoint, selected_midpoints, cluster_range, max_from_region)):
                    bisect.insort(selected_midpoints, seg.midpoint)
                    selected.append(seg)

        # Step 3: Greedy fill by score
        scored = sorted(sorted_segments, key=score_func, reverse=True)
        selected_ids = {id(s) for s in selected}
        for seg in scored:
            if len(selected) >= n:
                break
            if id(seg) not in selected_ids:
                if (self._respects_spacing(seg.midpoint, selected_midpoints, min_spacing)
                        and self._within_cluster_limit(seg.midpoint, selected_midpoints, cluster_range, max_from_region)):
                    bisect.insort(selected_midpoints, seg.midpoint)
                    selected.append(seg)
                    selected_ids.add(id(seg))

        # Step 4: Fallback if still short — try with cluster limit first, then without
        if len(selected) < n:
            for seg in scored:
                if len(selected) >= n:
                    break
                if id(seg) not in selected_ids:
                    if self._within_cluster_limit(seg.midpoint, selected_midpoints, cluster_range, max_from_region):
                        bisect.insort(selected_midpoints, seg.midpoint)
                        selected.append(seg)
                        selected_ids.add(id(seg))
        if len(selected) < n:
            for seg in scored:
                if len(selected) >= n:
                    break
                if id(seg) not in selected_ids:
                    selected.append(seg)
                    selected_ids.add(id(seg))

        # Sort chronologically and trim
        selected.sort(key=lambda s: s.midpoint)
        return selected[:n]

    def _within_cluster_limit(
        self,
        midpoint: float,
        sorted_midpoints: list[float],
        cluster_range: float,
        max_count: int,
    ) -> bool:
        """Check that fewer than max_count selected midpoints exist within ±cluster_range."""
        lo = bisect.bisect_left(sorted_midpoints, midpoint - cluster_range)
        hi = bisect.bisect_right(sorted_midpoints, midpoint + cluster_range)
        return (hi - lo) < max_count

    def _respects_spacing(
        self,
        midpoint: float,
        selected_midpoints: list[float],
        min_spacing: float,
    ) -> bool:
        """Check if a midpoint is at least min_spacing from all selected midpoints."""
        if not selected_midpoints:
            return True
        pos = bisect.bisect_left(selected_midpoints, midpoint)
        if pos < len(selected_midpoints) and abs(selected_midpoints[pos] - midpoint) < min_spacing:
            return False
        if pos > 0 and abs(selected_midpoints[pos - 1] - midpoint) < min_spacing:
            return False
        return True

    def _resolve_include_segments(
        self,
        sorted_segments: list[VideoSegment],
        midpoints: list[float],
    ) -> tuple[list[VideoSegment], list[float]]:
        """Resolve must-include timestamps to their containing segments.

        Returns (include_segments, include_anchors).
        """
        include_segments: list[VideoSegment] = []
        include_anchors: list[float] = []
        for ts in self.config.include_timestamps:
            seg = self._find_segment_at(sorted_segments, midpoints, ts)
            if seg is not None:
                include_segments.append(seg)
                include_anchors.append(ts)
        return include_segments, include_anchors

    def _merge_low_energy_intervals(
        self,
        intervals: list[tuple[BeatInfo, BeatInfo]],
        sections: list[MusicSection],
        target_count: int,
    ) -> list[tuple[BeatInfo, BeatInfo]]:
        """Merge adjacent intervals to reduce count, preferring low-energy sections.

        Merges the pair whose combined midpoint has the lowest energy first.
        Skips pairs whose combined duration would exceed max_segment_duration.
        """
        max_dur = self.config.max_segment_duration
        merged = list(intervals)
        while len(merged) > target_count and len(merged) > 1:
            # Find the pair with lowest energy to merge, respecting duration cap
            best_idx = None
            best_energy = float('inf')
            for i in range(len(merged) - 1):
                combined_dur = merged[i + 1][1].timestamp - merged[i][0].timestamp
                if combined_dur > max_dur:
                    continue  # Skip: would exceed max duration
                mid = (merged[i][0].timestamp + merged[i + 1][1].timestamp) / 2
                energy = self._energy_at(mid, sections)
                if energy < best_energy:
                    best_energy = energy
                    best_idx = i
            if best_idx is None:
                break  # No valid merge possible without exceeding duration cap
            # Merge pair: keep start of first, end of second
            new_interval = (merged[best_idx][0], merged[best_idx + 1][1])
            merged[best_idx:best_idx + 2] = [new_interval]
        return merged

    def _compute_global_energy(
        self,
        sections: list[MusicSection],
        video_duration: float,
    ) -> float:
        """Compute the weighted average energy across all sections."""
        if not sections:
            return 0.5
        total_weight = 0.0
        weighted_energy = 0.0
        for s in sections:
            dur = s.end_time - s.start_time
            weighted_energy += s.energy * dur
            total_weight += dur
        return weighted_energy / total_weight if total_weight > 0 else 0.5

    def _energy_at(self, timestamp: float, sections: list[MusicSection]) -> float:
        """Get the energy level at a given timestamp from music sections."""
        for s in sections:
            if s.start_time <= timestamp < s.end_time:
                return s.energy
        # Fallback: nearest section or default
        if sections:
            closest = min(sections, key=lambda s: abs(
                (s.start_time + s.end_time) / 2 - timestamp
            ))
            return closest.energy
        return 0.5

    @staticmethod
    def _coefficient_of_variation(values: list[float]) -> float:
        """Compute coefficient of variation (std/mean) of a list of values."""
        if len(values) < 2:
            return 0.0
        mean = statistics.mean(values)
        if mean == 0:
            return 0.0
        return statistics.stdev(values) / mean

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

    def _find_segment_at(
        self,
        sorted_segments: list[VideoSegment],
        midpoints: list[float],
        timestamp: float,
    ) -> VideoSegment | None:
        """Find the segment that contains the given timestamp using binary search."""
        pos = bisect.bisect_left(midpoints, timestamp)

        best = None
        for i in range(max(0, pos - 5), min(len(sorted_segments), pos + 5)):
            seg = sorted_segments[i]
            if seg.start_time <= timestamp <= seg.end_time:
                best = seg
                break

        if best is not None:
            return best

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
            start = anchor - needed_duration / 2
            end = anchor + needed_duration / 2
            if start < segment.start_time:
                start = segment.start_time
                end = start + needed_duration
            if end > segment.end_time:
                end = segment.end_time
                start = end - needed_duration
            return max(start, segment.start_time), min(end, segment.end_time)

        excess = available - needed_duration
        start = segment.start_time + excess / 2
        end = start + needed_duration
        return start, end

    def _merge_continuous(self, decisions: list[EditDecision]) -> list[EditDecision]:
        """Merge consecutive decisions whose source positions are adjacent.

        Consecutive decisions that pick from nearby source positions
        (gap < segment_window) get merged into a single longer clip.
        Merging stops when the resulting clip would exceed max_segment_duration.
        """
        if len(decisions) <= 1:
            return decisions

        threshold = self.config.segment_window
        max_dur = self.config.max_segment_duration
        merged: list[EditDecision] = []
        group_start = decisions[0]
        group_source_start = decisions[0].source_start
        group_target_end = decisions[0].target_end

        for i in range(1, len(decisions)):
            prev = decisions[i - 1]
            curr = decisions[i]
            gap = curr.source_start - prev.source_end
            would_be_duration = curr.target_end - group_start.target_start

            if gap < threshold and would_be_duration <= max_dur:
                group_target_end = curr.target_end
            else:
                total_dur = group_target_end - group_start.target_start
                flushed_source_end = group_source_start + total_dur
                merged.append(EditDecision(
                    beat_index=group_start.beat_index,
                    source_start=group_source_start,
                    source_end=flushed_source_end,
                    target_start=group_start.target_start,
                    target_end=group_target_end,
                    interest_score=group_start.interest_score,
                ))
                group_start = curr
                # Duration cap break: advance source past flushed clip
                # Gap break: start fresh at curr's source position
                if gap < threshold:
                    group_source_start = flushed_source_end
                else:
                    group_source_start = curr.source_start
                group_target_end = curr.target_end

        total_dur = group_target_end - group_start.target_start
        merged.append(EditDecision(
            beat_index=group_start.beat_index,
            source_start=group_source_start,
            source_end=group_source_start + total_dur,
            target_start=group_start.target_start,
            target_end=group_target_end,
            interest_score=group_start.interest_score,
        ))

        # Eliminate any remaining source overlaps between groups
        for i in range(1, len(merged)):
            prev_end = merged[i - 1].source_end
            if merged[i].source_start < prev_end:
                target_dur = merged[i].target_end - merged[i].target_start
                merged[i] = EditDecision(
                    beat_index=merged[i].beat_index,
                    source_start=prev_end,
                    source_end=prev_end + target_dur,
                    target_start=merged[i].target_start,
                    target_end=merged[i].target_end,
                    interest_score=merged[i].interest_score,
                )

        return merged
