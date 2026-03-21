"""Energy-driven cut point selection.

Selects which beats become cut points based on musical energy sections.
High-energy sections produce more cuts; low-energy sections produce fewer.
"""

import math

from trailvideocut.audio.models import BeatInfo, MusicSection


def energy_to_density(
    energy: float, tempo: float, min_segment: float, max_segment: float
) -> float:
    """Map energy [0,1] to a target cut density (cuts/second).

    energy=1.0 -> cut on every beat (density = tempo/60)
    energy=0.0 -> cut as infrequently as allowed (density = 1/max_segment)

    Physical min_segment constraints are enforced in select_cut_points_for_section.
    """
    max_density = min(tempo / 60.0, 1.0 / min_segment)
    min_density = 1.0 / max_segment
    scaled = energy ** 3.0
    return min_density + scaled * (max_density - min_density)


def select_cut_points_for_section(
    beats: list[BeatInfo],
    target_density: float,
    min_segment: float,
    max_segment: float,
) -> list[BeatInfo]:
    """Select which beats within a section become cut points.

    Window-based scoring: when the ideal next-cut time is reached,
    evaluate all beats in a window and pick the one with the best
    combined strength + timing score.
    """
    if not beats:
        return []

    target_interval = 1.0 / target_density if target_density > 0 else max_segment
    effective_interval = max(target_interval, min_segment)

    cut_points = [beats[0]]
    ideal_next = beats[0].timestamp + effective_interval

    i = 1
    while i < len(beats):
        beat = beats[i]
        time_since_last = beat.timestamp - cut_points[-1].timestamp

        # Skip beats too close to last cut
        if time_since_last < min_segment:
            i += 1
            continue

        # Force a cut if gap grows too large — search backward for last valid beat
        if time_since_last >= max_segment:
            chosen, chosen_idx = beat, i
            for k in range(i - 1, 0, -1):
                k_gap = beats[k].timestamp - cut_points[-1].timestamp
                if k_gap < min_segment:
                    break
                if k_gap < max_segment:
                    chosen, chosen_idx = beats[k], k
                    break
            cut_points.append(chosen)
            ideal_next = chosen.timestamp + effective_interval
            i = chosen_idx + 1
            continue

        # Only start evaluating once we're near the ideal time
        if beat.timestamp < ideal_next - 0.05:
            i += 1
            continue

        # Collect candidates in a window extending past the current beat
        window_end = max(beat.timestamp, ideal_next) + effective_interval * 0.5
        window_half = max(effective_interval * 0.5, 0.01)
        candidates: list[tuple[BeatInfo, int]] = []
        for j in range(i, len(beats)):
            cand = beats[j]
            if cand.timestamp > window_end:
                break
            cand_gap = cand.timestamp - cut_points[-1].timestamp
            if cand_gap < min_segment:
                continue
            if cand_gap >= max_segment:
                # Must cut here — but keep already-collected valid candidates
                if not candidates:
                    candidates = [(cand, j)]
                break
            candidates.append((cand, j))

        if not candidates:
            i += 1
            continue

        # Score each candidate: strength * proximity, with downbeat bonus
        best_beat = candidates[0][0]
        best_score = -1.0
        for cand, _ in candidates:
            distance = abs(cand.timestamp - ideal_next)
            proximity = max(0.0, 1.0 - distance / window_half)
            score = 0.4 * proximity + 0.4 * cand.strength
            if cand.is_downbeat:
                score += 0.2
            if score > best_score:
                best_score = score
                best_beat = cand

        cut_points.append(best_beat)
        ideal_next = best_beat.timestamp + effective_interval
        # Advance i past the selected beat
        while i < len(beats) and beats[i].timestamp <= best_beat.timestamp:
            i += 1

    return cut_points


def select_cut_points(
    beats: list[BeatInfo],
    sections: list[MusicSection],
    tempo: float,
    min_segment: float,
    max_segment: float,
) -> list[BeatInfo]:
    """Select cut points from all beats using energy-driven density per section.

    Returns a subset of beats that will serve as cut boundaries.
    """
    if not sections or not beats:
        return beats

    cut_points: list[BeatInfo] = []

    for section in sections:
        section_beats = [
            b for b in beats
            if section.start_time <= b.timestamp < section.end_time
        ]
        if not section_beats:
            continue

        density = energy_to_density(section.energy, tempo, min_segment, max_segment)
        section_cuts = select_cut_points_for_section(
            section_beats, density, min_segment, max_segment
        )

        # At section boundaries, swap instead of drop so every section
        # contributes at least its first beat-aligned cut point.
        if cut_points and section_cuts:
            if section_cuts[0].timestamp - cut_points[-1].timestamp < min_segment:
                cut_points[-1] = section_cuts.pop(0)

        cut_points.extend(section_cuts)

    # Ensure a final beat at the end of the song
    if beats and (not cut_points or cut_points[-1].timestamp < beats[-1].timestamp):
        if not cut_points or (beats[-1].timestamp - cut_points[-1].timestamp) >= min_segment:
            cut_points.append(beats[-1])

    # Safety net: split any remaining gaps > max_segment with synthetic beats
    cut_points = _enforce_max_segment(cut_points, beats, max_segment)

    return cut_points


def _enforce_max_segment(
    cut_points: list[BeatInfo],
    beats: list[BeatInfo],
    max_segment: float,
) -> list[BeatInfo]:
    """Insert synthetic beats to break any gap exceeding max_segment.

    First tries to use existing beats from the full beat list. Falls back to
    evenly-spaced synthetic beats if no real beat is available.
    """
    if len(cut_points) < 2:
        return cut_points

    # Index beats by timestamp for fast lookup
    beat_set = {round(b.timestamp, 6) for b in cut_points}
    result: list[BeatInfo] = [cut_points[0]]

    for cp in cut_points[1:]:
        while cp.timestamp - result[-1].timestamp > max_segment + 1e-9:
            gap = cp.timestamp - result[-1].timestamp
            # Try to find a real beat near the max_segment boundary
            target = result[-1].timestamp + max_segment
            best = None
            for b in beats:
                if b.timestamp <= result[-1].timestamp:
                    continue
                if b.timestamp >= cp.timestamp:
                    break
                if round(b.timestamp, 6) in beat_set:
                    continue
                if b.timestamp <= target:
                    best = b
            if best is not None:
                result.append(best)
                beat_set.add(round(best.timestamp, 6))
            else:
                # Insert evenly-spaced synthetic beats
                n_splits = math.ceil(gap / max_segment)
                step = gap / n_splits
                ts = result[-1].timestamp + step
                result.append(BeatInfo(
                    timestamp=ts,
                    strength=0.0,
                    is_downbeat=False,
                ))
                beat_set.add(round(ts, 6))
        result.append(cp)

    return result
