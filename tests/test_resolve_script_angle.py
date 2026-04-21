"""Rotation-aware plate export tests for the DaVinci Fusion Lua generator.

Covers OpenSpec `export-davinci-blur-rotation` tasks 1.2–1.5 and 4.2: the
generated Lua script must emit a keyframed ``Angle`` spline on each
``RectangleMask`` so rotated plate boxes are blurred at the same
orientation the preview overlay displays.  The sign flip (``-plate_angle``)
accounts for Fusion's Y-up convention vs. the PlateBox Y-down convention.
"""

from __future__ import annotations

import re

from trailvideocut.editor.resolve_script import (
    _SCRIPT_TEMPLATE,
    _generate_lua_script_for_clip,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _box(x, y, w, h, angle=0.0, include_angle=True):
    """Build a plate-box dict as the exporter would emit it."""
    d = {"x": float(x), "y": float(y), "w": float(w), "h": float(h)}
    if include_angle:
        d["angle"] = float(angle)
    return d


def _detections_for_track(frame_range, angle, include_angle=True):
    """Build a detections dict (frame_str -> [box]) for a single plate track.

    Boxes are close enough in centre position that ``_group_into_tracks``
    chains them into a single track.
    """
    return {
        str(f): [_box(0.4, 0.4, 0.1, 0.05, angle=angle, include_angle=include_angle)]
        for f in frame_range
    }


def _angle_keyframe_lines(lua: str, mask_var: str = "mask1") -> list[tuple[str, str]]:
    """Extract (frame_expr, value_expr) for every ``<mask>.Angle[...] = ...``.

    Uses string comparison for the value so the assertions read naturally
    against the Lua source (``"-30.0"`` not ``-30.0``).
    """
    pattern = re.compile(
        rf"^{re.escape(mask_var)}\.Angle\[(.+?)\]\s*=\s*(.+)$",
        re.MULTILINE,
    )
    return pattern.findall(lua)


# ---------------------------------------------------------------------------
# 1.2  Rotated track emits Angle spline with sign-flipped value
# ---------------------------------------------------------------------------


def test_angle_spline_emitted_for_rotated_track():
    detections = _detections_for_track(range(10, 15), angle=30.0)
    lua = _generate_lua_script_for_clip(
        clip_name="clip0", detections=detections,
        frame_count=50, src_start_frame=0,
    )

    # The spline is declared exactly once.
    assert lua.count("mask1.Angle = BezierSpline({})") == 1, lua

    # At least one per-frame keyframe lands at -30.0 (Y-down → Y-up flip).
    kfs = _angle_keyframe_lines(lua)
    per_frame_values = [
        v for frame_expr, v in kfs
        if frame_expr.startswith("comp_for_rel(") and v.strip() not in {"0", "0.0"}
    ]
    assert per_frame_values, f"no non-zero Angle keyframes emitted: {kfs}"
    assert all(v.strip() == "-30.0" for v in per_frame_values), per_frame_values


# ---------------------------------------------------------------------------
# 1.3  Axis-aligned track emits only zero Angle keyframes
# ---------------------------------------------------------------------------


def test_angle_spline_zero_for_axis_aligned_track():
    detections = _detections_for_track(range(10, 15), angle=0.0)
    lua = _generate_lua_script_for_clip(
        clip_name="clip0", detections=detections,
        frame_count=50, src_start_frame=0,
    )

    assert lua.count("mask1.Angle = BezierSpline({})") == 1, lua
    kfs = _angle_keyframe_lines(lua)
    assert kfs, "no Angle keyframes emitted at all"
    for frame_expr, value in kfs:
        assert value.strip() in {"0", "0.0", "-0.0"}, (frame_expr, value)


# ---------------------------------------------------------------------------
# 1.4  Mid-clip track writes zero Angle at both boundary frames
# ---------------------------------------------------------------------------


def test_angle_boundary_keyframes_are_zero():
    # Track spans clip-relative detection frames 10..14.  The Lua generator
    # densifies keyframes across ``[min - _NEAREST_WINDOW, max + _NEAREST_WINDOW]``
    # (window = 2), so the boundary zero-keyframes land at 7 and 17.  Clip holds
    # 50 frames total so both boundaries fall strictly inside the range.
    detections = _detections_for_track(range(10, 15), angle=30.0)
    lua = _generate_lua_script_for_clip(
        clip_name="clip0", detections=detections,
        frame_count=50, src_start_frame=0,
    )

    kfs = _angle_keyframe_lines(lua)
    by_frame = {frame_expr: value.strip() for frame_expr, value in kfs}

    assert by_frame.get("comp_for_rel(7)") in {"0", "0.0", "-0.0"}, by_frame
    assert by_frame.get("comp_for_rel(17)") in {"0", "0.0", "-0.0"}, by_frame
    # Sanity: every densified per-frame value carries the flipped angle.
    assert by_frame["comp_for_rel(10)"] == "-30.0", by_frame
    assert by_frame["comp_for_rel(14)"] == "-30.0", by_frame


# ---------------------------------------------------------------------------
# 1.5  Legacy dicts without an `angle` key default to 0.0
# ---------------------------------------------------------------------------


def test_legacy_dict_without_angle_defaults_to_zero():
    # Simulate an OTIO file written before rotation was serialized.
    detections = _detections_for_track(range(10, 15), angle=0.0, include_angle=False)
    lua = _generate_lua_script_for_clip(
        clip_name="clip0", detections=detections,
        frame_count=50, src_start_frame=0,
    )

    # Must not crash, must still emit the Angle spline, and every keyframe
    # must be zero (we never fabricate a rotation the user never authored).
    assert lua.count("mask1.Angle = BezierSpline({})") == 1, lua
    for _frame_expr, value in _angle_keyframe_lines(lua):
        assert value.strip() in {"0", "0.0", "-0.0"}, value


# ---------------------------------------------------------------------------
# 4.2  In-Resolve Python path references Angle + legacy default
# ---------------------------------------------------------------------------


def test_in_resolve_python_path_references_angle():
    """The embedded in-Resolve automation script must set ``"Angle"`` per
    frame and default a missing ``angle`` key to 0.0 (mirroring the offline
    Lua generator's contract).
    """
    assert '"Angle"' in _SCRIPT_TEMPLATE
    assert 'box.get("angle", 0.0)' in _SCRIPT_TEMPLATE
