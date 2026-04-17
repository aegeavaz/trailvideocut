"""Must-include marks: timestamps the clip selector pins into the final edit.

Data model (plain `list[float]`), and JSON sidecar persistence at
`{video_stem}.marks.json`. Mirrors ``video/exclusions.py``; the loader also
accepts the pre-versioning bare-array format for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_VERSION = 1
_SUPPORTED_VERSIONS = {1}


def get_marks_path(video_path: str | Path) -> Path:
    """Return the sidecar path for a video: ``<stem>.marks.json``."""
    p = Path(video_path)
    return p.with_suffix(".marks.json")


def save_marks(video_path: str | Path, marks: list[float]) -> None:
    """Serialize *marks* (seconds) to the sidecar JSON file next to *video_path*.

    Marks are sorted ascending on write. Logs a warning on I/O failure; does
    not raise, so a read-only location cannot disrupt an interactive session.
    """
    path = get_marks_path(video_path)
    sorted_marks = sorted(float(m) for m in marks)
    payload = {
        "version": _VERSION,
        "video_filename": Path(video_path).name,
        "marks": sorted_marks,
    }
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except PermissionError:
        logger.warning("Cannot save marks: permission denied for %s", path)
    except OSError as exc:
        logger.warning("Cannot save marks to %s: %s", path, exc)


def load_marks(video_path: str | Path) -> list[float]:
    """Load marks from the sidecar file, if it exists.

    Returns an empty list (and logs a warning, except for the missing-file
    case) on any recoverable failure:
      - missing sidecar (no warning — common case)
      - unparseable JSON
      - top-level value neither object nor array
      - unknown schema version
      - filename mismatch
      - malformed entries

    Accepts the legacy bare-array format (``[1.2, 3.4]``) written by earlier
    releases; non-numeric entries in such a file cause the whole file to be
    discarded rather than silently dropping individual entries.
    """
    path = get_marks_path(video_path)
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read marks file %s: %s", path, exc)
        return []

    if isinstance(raw, list):
        return _parse_legacy_array(raw, path)

    if not isinstance(raw, dict):
        logger.warning("Marks file %s has unsupported top-level type %s", path, type(raw).__name__)
        return []

    version = raw.get("version")
    if version not in _SUPPORTED_VERSIONS:
        logger.warning(
            "Marks file %s has unsupported version %r (expected one of %s)",
            path, version, sorted(_SUPPORTED_VERSIONS),
        )
        return []

    expected_name = Path(video_path).name
    stored_name = raw.get("video_filename")
    if stored_name != expected_name:
        logger.warning(
            "Marks file %s references %r but current video is %r — discarding",
            path, stored_name, expected_name,
        )
        return []

    raw_marks = raw.get("marks")
    if not isinstance(raw_marks, list):
        return []

    result: list[float] = []
    for entry in raw_marks:
        if isinstance(entry, bool) or not isinstance(entry, (int, float)):
            logger.warning("Marks file %s has malformed entry %r — discarding file", path, entry)
            return []
        result.append(float(entry))
    result.sort()
    return result


def _parse_legacy_array(raw: list, path: Path) -> list[float]:
    """Parse a bare-array sidecar written by the pre-versioning release."""
    result: list[float] = []
    for entry in raw:
        if isinstance(entry, bool) or not isinstance(entry, (int, float)):
            logger.warning(
                "Marks file %s has malformed legacy entry %r — discarding file",
                path, entry,
            )
            return []
        result.append(float(entry))
    result.sort()
    return result


def delete_marks(video_path: str | Path) -> None:
    """Delete the sidecar file if it exists. Logs (not raises) on I/O error."""
    path = get_marks_path(video_path)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Cannot delete marks file %s: %s", path, exc)
