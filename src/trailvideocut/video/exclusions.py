"""Exclusion ranges: time spans of the source video to skip during clip selection.

Data model, validation helpers, and JSON sidecar persistence
(`{video_stem}.exclusions.json`). Mirrors the plate sidecar pattern.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_VERSION = 1
_SUPPORTED_VERSIONS = {1}


@dataclass
class ExclusionRange:
    """A `[start, end]` time span (seconds) of the source video to skip."""

    start: float
    end: float

    def __post_init__(self) -> None:
        self.start = float(self.start)
        self.end = float(self.end)
        if not (self.start < self.end):
            raise ValueError(
                f"ExclusionRange requires start < end (got start={self.start}, end={self.end})"
            )


def overlaps(a: ExclusionRange, b: ExclusionRange) -> bool:
    """Return True iff two ranges overlap. Touching endpoints are NOT overlap."""
    return a.start < b.end and b.start < a.end


def contains(ranges: list[ExclusionRange], t: float) -> bool:
    """Return True iff `t` is strictly inside any range (start < t < end)."""
    for r in ranges:
        if r.start < t < r.end:
            return True
    return False


def validate_exclusions(
    ranges: list[ExclusionRange],
    video_duration: float,
    include_timestamps: list[float],
) -> None:
    """Validate exclusion ranges against the video duration and include timestamps.

    Raises ``ValueError`` on:
      - inverted range (start >= end) — already rejected at construction, but
        guarded here in case raw tuples were converted without using the
        dataclass.
      - range outside ``[0, video_duration]``.
      - any two ranges that overlap.
      - any include timestamp falling strictly inside any range.
    """
    for r in ranges:
        if not (r.start < r.end):
            raise ValueError(
                f"Exclusion range is inverted: start={r.start}, end={r.end}"
            )
        if r.start < 0 or r.end > video_duration:
            raise ValueError(
                f"Exclusion range [{r.start}, {r.end}] is outside video duration "
                f"[0, {video_duration}]"
            )

    for i in range(len(ranges)):
        for j in range(i + 1, len(ranges)):
            if overlaps(ranges[i], ranges[j]):
                raise ValueError(
                    f"Exclusion ranges overlap: "
                    f"[{ranges[i].start}, {ranges[i].end}] and "
                    f"[{ranges[j].start}, {ranges[j].end}]"
                )

    for ts in include_timestamps:
        for r in ranges:
            if r.start < ts < r.end:
                raise ValueError(
                    f"Include timestamp {ts} falls inside exclusion range "
                    f"[{r.start}, {r.end}]"
                )


def get_exclusions_path(video_path: str | Path) -> Path:
    """Return the sidecar path for a video: ``<stem>.exclusions.json``."""
    p = Path(video_path)
    return p.with_suffix(".exclusions.json")


def save_exclusions(
    video_path: str | Path,
    ranges: list[ExclusionRange],
) -> None:
    """Serialize *ranges* to the sidecar JSON file next to *video_path*.

    Logs a warning on permission errors; does not raise.
    """
    path = get_exclusions_path(video_path)
    payload = {
        "version": _VERSION,
        "video_filename": Path(video_path).name,
        "ranges": [{"start": float(r.start), "end": float(r.end)} for r in ranges],
    }
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except PermissionError:
        logger.warning("Cannot save exclusions: permission denied for %s", path)
    except OSError as exc:
        logger.warning("Cannot save exclusions to %s: %s", path, exc)


def load_exclusions(video_path: str | Path) -> list[ExclusionRange]:
    """Load exclusion ranges from the sidecar file, if it exists.

    Returns an empty list (and logs a warning) on:
      - missing sidecar (no warning — that is the common case)
      - corrupt JSON
      - unknown version
      - filename mismatch
      - malformed schema
    """
    path = get_exclusions_path(video_path)
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read exclusions file %s: %s", path, exc)
        return []

    if not isinstance(raw, dict):
        logger.warning("Exclusions file %s is not an object", path)
        return []

    version = raw.get("version")
    if version not in _SUPPORTED_VERSIONS:
        logger.warning(
            "Exclusions file %s has unsupported version %r (expected one of %s)",
            path, version, sorted(_SUPPORTED_VERSIONS),
        )
        return []

    expected_name = Path(video_path).name
    stored_name = raw.get("video_filename")
    if stored_name != expected_name:
        logger.warning(
            "Exclusions file %s references %r but current video is %r — discarding",
            path, stored_name, expected_name,
        )
        return []

    raw_ranges = raw.get("ranges")
    if not isinstance(raw_ranges, list):
        logger.warning("Exclusions file %s has no 'ranges' array", path)
        return []

    result: list[ExclusionRange] = []
    for entry in raw_ranges:
        if not isinstance(entry, dict):
            continue
        try:
            start = float(entry["start"])
            end = float(entry["end"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Skipping malformed exclusion entry %r in %s", entry, path)
            continue
        try:
            result.append(ExclusionRange(start=start, end=end))
        except ValueError as exc:
            logger.warning("Skipping invalid exclusion entry in %s: %s", path, exc)
    return result


def delete_exclusions(video_path: str | Path) -> None:
    """Delete the sidecar file if it exists."""
    path = get_exclusions_path(video_path)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Cannot delete exclusions file %s: %s", path, exc)
