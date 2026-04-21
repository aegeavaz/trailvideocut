"""Persist plate detection results as JSON sidecar files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from trailvideocut.plate.models import ClipPlateData, PlateBox

_VERSION = 2  # v2 adds per-clip phone_zones; v1 files still load with empty zones.
_SUPPORTED_VERSIONS = {1, 2}
logger = logging.getLogger(__name__)


def get_plates_path(video_path: str | Path) -> Path:
    """Return the sidecar path for a video: ``<stem>.plates.json``."""
    p = Path(video_path)
    return p.with_suffix(".plates.json")


def save_plates(
    video_path: str | Path,
    plate_data: dict[int, ClipPlateData],
) -> None:
    """Serialize *plate_data* to the sidecar JSON file next to *video_path*.

    Raises nothing on permission errors — logs a warning instead.
    """
    path = get_plates_path(video_path)
    payload = {
        "version": _VERSION,
        "video_file": Path(video_path).name,
        "clips": {},
    }
    for clip_idx, cpd in plate_data.items():
        detections: dict[str, list[dict]] = {}
        for frame, boxes in cpd.detections.items():
            entries: list[dict] = []
            for b in boxes:
                entry: dict = {
                    "x": float(b.x),
                    "y": float(b.y),
                    "w": float(b.w),
                    "h": float(b.h),
                    "confidence": float(b.confidence),
                    "manual": bool(b.manual),
                }
                # Omit ``angle`` when axis-aligned so older readers (and diffs)
                # stay identical to the pre-refinement sidecar format.
                if float(b.angle) != 0.0:
                    entry["angle"] = float(b.angle)
                entries.append(entry)
            detections[str(frame)] = entries
        clip_payload: dict = {
            "clip_index": cpd.clip_index,
            "detections": detections,
        }
        if cpd.phone_zones:
            clip_payload["phone_zones"] = {
                str(frame): [[float(z[0]), float(z[1]), float(z[2]), float(z[3])]
                             for z in zones]
                for frame, zones in cpd.phone_zones.items()
            }
        payload["clips"][str(clip_idx)] = clip_payload
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except PermissionError:
        logger.warning("Cannot save plates: permission denied for %s", path)


def load_plates(
    video_path: str | Path,
    valid_clip_indices: set[int] | None = None,
) -> dict[int, ClipPlateData]:
    """Load plate data from the sidecar file, if it exists.

    Returns an empty dict on missing file, parse errors, or version mismatch.
    When *valid_clip_indices* is provided, clips not in the set are discarded.
    """
    path = get_plates_path(video_path)
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read plates file %s: %s", path, exc)
        return {}

    if not isinstance(raw, dict) or raw.get("version") not in _SUPPORTED_VERSIONS:
        logger.warning("Unsupported plates file version in %s", path)
        return {}

    result: dict[int, ClipPlateData] = {}
    for clip_key, clip_obj in raw.get("clips", {}).items():
        try:
            clip_idx = int(clip_key)
        except (ValueError, TypeError):
            continue
        if valid_clip_indices is not None and clip_idx not in valid_clip_indices:
            continue
        detections: dict[int, list[PlateBox]] = {}
        for frame_key, box_list in clip_obj.get("detections", {}).items():
            try:
                frame_num = int(frame_key)
            except (ValueError, TypeError):
                continue
            boxes = []
            for b in box_list:
                try:
                    angle = float(b.get("angle", 0.0))
                except (TypeError, ValueError):
                    logger.warning(
                        "Malformed angle in plates file %s (frame %s); defaulting to 0.0",
                        path,
                        frame_key,
                    )
                    angle = 0.0
                boxes.append(
                    PlateBox(
                        x=float(b["x"]),
                        y=float(b["y"]),
                        w=float(b["w"]),
                        h=float(b["h"]),
                        confidence=float(b.get("confidence", 0.0)),
                        manual=bool(b.get("manual", False)),
                        angle=angle,
                    )
                )
            if boxes:
                detections[frame_num] = boxes
        phone_zones: dict[int, list[tuple[float, float, float, float]]] = {}
        for frame_key, zone_list in clip_obj.get("phone_zones", {}).items():
            try:
                frame_num = int(frame_key)
            except (ValueError, TypeError):
                continue
            parsed = []
            for z in zone_list:
                if isinstance(z, (list, tuple)) and len(z) == 4:
                    parsed.append((float(z[0]), float(z[1]), float(z[2]), float(z[3])))
            if parsed:
                phone_zones[frame_num] = parsed
        result[clip_idx] = ClipPlateData(
            clip_index=clip_idx,
            detections=detections,
            phone_zones=phone_zones,
        )

    return result


def delete_plates(video_path: str | Path) -> None:
    """Delete the sidecar file if it exists."""
    path = get_plates_path(video_path)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Cannot delete plates file %s: %s", path, exc)
