"""Temporal continuity filter for plate detection results.

Eliminates sporadic detections that don't persist across consecutive frames.
Real plates appear in multiple frames with smooth spatial movement; false
positives tend to appear in only 1-2 isolated frames.
"""

from __future__ import annotations

from trailvideocut.plate.models import ClipPlateData, PlateBox


def filter_temporal_continuity(
    data: ClipPlateData,
    min_track_length: int = 3,
    max_center_distance: float = 0.05,
    max_frame_gap: int = 1,
) -> ClipPlateData:
    """Remove detections that don't persist across consecutive frames.

    Builds tracks by linking spatially similar detections across adjacent
    frames, then removes detections belonging to tracks shorter than
    *min_track_length*.

    Args:
        data: Detection results to filter.
        min_track_length: Minimum frames a detection must appear in to survive.
        max_center_distance: Max center-to-center distance (normalized coords)
            to link detections across frames.
        max_frame_gap: Max frame gap allowed within a track (set to every_n
            when using frame sampling).

    Returns:
        New ClipPlateData with filtered detections (input is not mutated).
    """
    if not data.detections:
        return ClipPlateData(clip_index=data.clip_index, detections={})

    # Separate manual vs auto boxes
    manual_by_frame: dict[int, list[PlateBox]] = {}
    auto_by_frame: dict[int, list[PlateBox]] = {}
    for frame, boxes in data.detections.items():
        manuals = [b for b in boxes if b.manual]
        autos = [b for b in boxes if not b.manual]
        if manuals:
            manual_by_frame[frame] = manuals
        if autos:
            auto_by_frame[frame] = autos

    # Build tracks greedily
    # Each track is a list of (frame, PlateBox) tuples
    active_tracks: list[list[tuple[int, PlateBox]]] = []
    finished_tracks: list[list[tuple[int, PlateBox]]] = []

    for frame in sorted(auto_by_frame):
        boxes = auto_by_frame[frame]
        used_tracks: set[int] = set()
        used_boxes: set[int] = set()

        # Build candidate matches: (track_idx, box_idx, distance)
        candidates: list[tuple[int, int, float]] = []
        for ti, track in enumerate(active_tracks):
            last_frame, last_box = track[-1]
            if frame - last_frame > max_frame_gap:
                continue
            for bi, box in enumerate(boxes):
                dist = _center_distance(last_box, box)
                if dist <= max_center_distance:
                    candidates.append((ti, bi, dist))

        # Greedy assignment: closest first
        candidates.sort(key=lambda c: c[2])
        for ti, bi, _ in candidates:
            if ti in used_tracks or bi in used_boxes:
                continue
            active_tracks[ti].append((frame, boxes[bi]))
            used_tracks.add(ti)
            used_boxes.add(bi)

        # Start new tracks for unmatched boxes
        for bi, box in enumerate(boxes):
            if bi not in used_boxes:
                active_tracks.append([(frame, box)])

        # Retire tracks that are too old
        still_active: list[list[tuple[int, PlateBox]]] = []
        for track in active_tracks:
            if frame - track[-1][0] > max_frame_gap:
                finished_tracks.append(track)
            else:
                still_active.append(track)
        active_tracks = still_active

    finished_tracks.extend(active_tracks)

    # Collect box ids from tracks that are long enough
    kept: set[int] = set()
    for track in finished_tracks:
        if len(track) >= min_track_length:
            for _, box in track:
                kept.add(id(box))

    # Rebuild detections dict
    new_detections: dict[int, list[PlateBox]] = {}
    for frame in sorted(data.detections):
        result_boxes: list[PlateBox] = []
        for box in auto_by_frame.get(frame, []):
            if id(box) in kept:
                result_boxes.append(box)
        for box in manual_by_frame.get(frame, []):
            result_boxes.append(box)
        if result_boxes:
            new_detections[frame] = result_boxes

    return ClipPlateData(clip_index=data.clip_index, detections=new_detections)


def _center_distance(a: PlateBox, b: PlateBox) -> float:
    """Euclidean distance between box centers in normalized coordinates."""
    ax = a.x + a.w / 2
    ay = a.y + a.h / 2
    bx = b.x + b.w / 2
    by = b.y + b.h / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
