"""Tests for the DaVinci Resolve / Fusion Lua script generator.

Covers:
- Coordinate conversion: PlateBox (Y-down image-relative) -> Fusion's
  RectangleMask (Y-up image-relative, Width/Height image-relative).
- Dense per-frame keyframes (one keyframe per comp frame, no Bezier
  interpolation drift between sparse keyframes).
- Nearest-detection-within-window lookup for comp frames that have no
  exact detection.
- Frame-number alignment between exporter and OTIO encoding (round-based,
  via _seconds_to_rational_time).
"""

from __future__ import annotations

import re

from trailvideocut.editor.exporter import _seconds_to_rational_time
from trailvideocut.editor.resolve_script import (
    _BLUR_SIZE_MAX,
    _BLUR_SIZE_MIN,
    _NEAREST_WINDOW,
    _compute_blur_sizes,
    _generate_lua_script_for_clip as _real_generate_lua_script_for_clip,
    _group_into_tracks,
    _nearest_box_for_frame,
)


def _generate_lua_script_for_clip(
    clip_name, detections, frame_count, src_start_frame=0,
):
    """Test wrapper that defaults src_start_frame to 0 (handle-free clip)."""
    return _real_generate_lua_script_for_clip(
        clip_name, detections, frame_count, src_start_frame,
    )


def _make_detections(boxes_at: dict[int, dict]) -> dict[str, list[dict]]:
    """Build a `detections` dict suitable for `_generate_lua_script_for_clip`.

    `boxes_at` maps frame_number -> a single box dict.
    """
    return {
        str(frame): [box]
        for frame, box in boxes_at.items()
    }


def _single_box_detections() -> dict[str, list[dict]]:
    """One plate at a known location across two adjacent frames.

    Box: x=0.4, y=0.45, w=0.2, h=0.05
    PlateBox center (Y-down) = (0.5, 0.475)
    Fusion's RectangleMask uses Y-UP image-relative coords, so the
    expected Fusion Center is (0.5, 1.0 - 0.475) = (0.5, 0.525).
    """
    return _make_detections({
        10: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
        11: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
    })


def _find_keyframe_lines(script: str, attr: str, mask_var: str = "mask1") -> list[str]:
    """Return all lines that look like '<mask>.<Attr>[comp_for_rel(N)] = ...'."""
    needle = f"{mask_var}.{attr}[comp_for_rel("
    return [ln.strip() for ln in script.splitlines() if needle in ln]


def _parse_keyframe_frame(line: str) -> int:
    """Parse the integer frame from a `mask.Attr[comp_for_rel(N)] = ...` line."""
    m = re.search(r"\[comp_for_rel\((\d+)\)\]", line)
    assert m, f"unparseable keyframe line: {line}"
    return int(m.group(1))


def _parse_center_xy(line: str) -> tuple[float, float]:
    m = re.search(r"\{([^,]+),\s*([^}]+)\}", line)
    assert m, f"unparseable center line: {line}"
    return float(m.group(1)), float(m.group(2))


def _parse_scalar_rhs(line: str) -> float:
    """Parse the scalar on the right-hand side of `... = <number>`."""
    m = re.search(r"=\s*([-+0-9.eE]+)\s*$", line)
    assert m, f"unparseable scalar line: {line}"
    return float(m.group(1))


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------


class TestLuaCoordinateConversion:
    """Coordinate conversion is now checked on the keyframe written for the
    actual detection frame (frames 10 and 11 in `_single_box_detections`).
    """

    def test_width_keyframe_is_passthrough(self):
        """Width is image-width-relative, same as PlateBox.w. No multiplier."""
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
        )
        width_lines = _find_keyframe_lines(script, "Width")
        # Frames 10 and 11 both have detections; frames 8, 9 are within the
        # nearest-neighbor window so they also get the same value via lookup.
        # Frame 7 has a zero-size boundary keyframe.
        assert width_lines, f"no Width keyframe lines:\n{script}"
        for line in width_lines:
            val = _parse_scalar_rhs(line)
            frame = _parse_keyframe_frame(line)
            if frame == 7:
                assert val == 0, line  # boundary keyframe
            else:
                assert val == 0.2, line
            assert "aspect" not in line, line

    def test_height_keyframe_is_passthrough(self):
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
        )
        height_lines = _find_keyframe_lines(script, "Height")
        assert height_lines
        for line in height_lines:
            val = _parse_scalar_rhs(line)
            frame = _parse_keyframe_frame(line)
            if frame == 7:
                assert val == 0, line  # boundary keyframe
            else:
                assert abs(val - 0.05) < 1e-9, line
            assert "aspect" not in line

    def test_center_y_is_inverted_for_y_up(self):
        """Center.Y = 1 - (PlateBox.y + h/2) = 1 - 0.475 = 0.525."""
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
        )
        center_lines = _find_keyframe_lines(script, "Center")
        assert center_lines
        for line in center_lines:
            cx, cy = _parse_center_xy(line)
            frame = _parse_keyframe_frame(line)
            assert cx == 0.5
            if frame == 7:
                assert abs(cy - 0.5) < 1e-9, line  # boundary keyframe
            else:
                assert abs(cy - 0.525) < 1e-9, line

    def test_center_x_is_passthrough(self):
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
        )
        center_lines = _find_keyframe_lines(script, "Center")
        for line in center_lines:
            cx, _ = _parse_center_xy(line)
            assert cx == 0.5
            assert "aspect" not in line


# ---------------------------------------------------------------------------
# Dense keyframes
# ---------------------------------------------------------------------------


class TestDenseKeyframes:
    def test_one_keyframe_per_frame_when_detections_dense(self):
        """When every clip frame has a detection, every comp frame has a
        keyframe — no delta-encoding skipping.
        """
        detections = _make_detections({
            f: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05}
            for f in range(10)
        })
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=10,
        )
        center_lines = _find_keyframe_lines(script, "Center")
        # Every comp frame in [0, 10) has a keyframe (10 total, one per frame).
        # No skipping for "identical to previous".
        frames = sorted(_parse_keyframe_frame(ln) for ln in center_lines)
        assert frames == list(range(10)), frames

    def test_keyframes_fill_gaps_via_nearest_neighbor(self):
        """Sparse detections within a single physical plate track get filled
        in via nearest-neighbor lookup within the +/- _NEAREST_WINDOW window.

        All detections share the same center so `_group_into_tracks` merges
        them into one track (otherwise distinct centers would split into
        separate tracks and each mask would only cover +/-window around its
        own single detection).
        """
        same_pos = {"x": 0.40, "y": 0.45, "w": 0.05, "h": 0.05}
        detections = _make_detections({
            0: dict(same_pos),
            3: dict(same_pos),
            7: dict(same_pos),
        })
        # frame_count=11 -> for the single merged track:
        #   frame 10 is 3 frames from the nearest detection (frame 7), beyond
        #   _NEAREST_WINDOW=2 -> no keyframe at frame 10.
        #   All other frames 0..9 are within +/-2 of at least one detection.
        #   Frame 10 gets a zero-size post-boundary keyframe (last_kf=9, 9+1<11).
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=11,
        )
        center_lines = _find_keyframe_lines(script, "Center")
        frames = sorted(_parse_keyframe_frame(ln) for ln in center_lines)
        # 0-9 are detection keyframes, 10 is zero-size boundary
        assert frames == list(range(11)), frames

    def test_no_keyframe_outside_window(self):
        """Comp frames more than _NEAREST_WINDOW away from any detection get
        no keyframe at all (except for the zero-size post-boundary keyframe)."""
        detections = _make_detections({
            0: {"x": 0.1, "y": 0.1, "w": 0.05, "h": 0.05},
        })
        # frame_count=10 -> frames 0,1,2 within window (dist 0,1,2),
        # frames 4..9 are >2 away -> no keyframes.
        # Frame 3 gets a zero-size post-boundary (last_kf=2, 2+1<10).
        # No pre-boundary since first_kf=0.
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=10,
        )
        center_lines = _find_keyframe_lines(script, "Center")
        frames = sorted(_parse_keyframe_frame(ln) for ln in center_lines)
        assert frames == [0, 1, 2, 3], frames

    def test_keyframe_does_not_union_neighbors(self):
        """The keyframe at frame N uses exactly the box from frame N (or the
        nearest detection), NOT a spatial union with N-1 / N+1.
        """
        # Two adjacent detections with different x positions.
        detections = _make_detections({
            5: {"x": 0.40, "y": 0.45, "w": 0.05, "h": 0.05},
            6: {"x": 0.60, "y": 0.45, "w": 0.05, "h": 0.05},
        })
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=8,
        )
        # Find the Width keyframe at frame 5 and assert it's still 0.05
        # (would be 0.25 if we were unioning with frame 6's box).
        width_lines = _find_keyframe_lines(script, "Width")
        widths_by_frame = {
            _parse_keyframe_frame(ln): _parse_scalar_rhs(ln)
            for ln in width_lines
        }
        assert widths_by_frame[5] == 0.05
        assert widths_by_frame[6] == 0.05


# ---------------------------------------------------------------------------
# _nearest_box_for_frame helper
# ---------------------------------------------------------------------------


class TestNearestBoxForFrame:
    def test_exact_hit(self):
        track = {5: {"x": 0.1}}
        assert _nearest_box_for_frame(track, 5) == {"x": 0.1}

    def test_prefers_earlier_on_ties(self):
        track = {3: {"label": "early"}, 7: {"label": "late"}}
        # frame 5 is dist 2 from both. Inner loop checks offset 1 first
        # (4 absent, 6 absent), then offset 2: prev=3 first -> "early".
        assert _nearest_box_for_frame(track, 5) == {"label": "early"}

    def test_returns_none_outside_window(self):
        track = {0: {"x": 0.1}}
        assert _nearest_box_for_frame(track, 0 + _NEAREST_WINDOW + 1) is None

    def test_within_window(self):
        track = {10: {"x": 0.1}}
        for offset in range(-_NEAREST_WINDOW, _NEAREST_WINDOW + 1):
            assert _nearest_box_for_frame(track, 10 + offset) == {"x": 0.1}


# ---------------------------------------------------------------------------
# Frame-number alignment with OTIO
# ---------------------------------------------------------------------------


class TestExporterFrameAlignment:
    def test_seconds_to_rational_time_uses_round(self):
        """Sanity check the OTIO encoding helper: round(t * fps).

        For t=0.522 and fps=23.976:
          int (truncation) = 12
          round            = 13
        These differ -- and we want the *exporter* to use the round() value
        so OTIO and the Fusion script agree.
        """
        rt = _seconds_to_rational_time(0.522, 23.976)
        assert rt.value == round(0.522 * 23.976)
        assert rt.value != int(0.522 * 23.976)


class TestSrcStartFrameOffset:
    """The runtime offset machinery that compensates for crossfade leading
    handle frames in Resolve's clip Fusion comp.

    The clip's plate at clip-relative frame N maps to comp frame
    `clip_offset + N`, where `clip_offset = SRC_START_FRAME +
    MediaIn1.ClipTimeStart` is computed at runtime in Lua.  The Python
    generator must:
      1. Embed `local SRC_START_FRAME = <value>` in the preamble.
      2. Read `MediaIn1.ClipTimeStart` (or equivalent) at runtime.
      3. Compute `local clip_offset = SRC_START_FRAME + mi_clip_start`.
      4. Write all keyframes against `clip_offset + N`.
    """

    def test_src_start_frame_constant_is_embedded(self):
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
            src_start_frame=3812,
        )
        assert "local SRC_START_FRAME = 3812" in script

    def test_clip_offset_is_computed_from_clip_time_start(self):
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
            src_start_frame=3812,
        )
        assert "media_in:GetInput('ClipTimeStart')" in script
        # `clip_offset` is declared separately above an if/else that
        # selects between an empirical KEYFRAME_OFFSET_OVERRIDE branch and
        # the auto-computed value, so the assignment line is not prefixed
        # with `local`.  We just assert the expression that matters.
        assert "clip_offset = SRC_START_FRAME + mi_clip_start" in script

    def test_keyframes_use_comp_for_rel_not_render_start(self):
        """Every keyframe write must reference comp_for_rel() (the piecewise
        offset function), not raw clip_offset or the comp's render_start.
        """
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
            src_start_frame=3812,
        )
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("mask1.Center[") or \
               stripped.startswith("mask1.Width[") or \
               stripped.startswith("mask1.Height[") or \
               stripped.startswith("blur1.XBlurSize["):
                assert "comp_for_rel(" in stripped, stripped
                assert "frame_offset" not in stripped, stripped

    def test_src_start_frame_zero_for_handle_free_clip(self):
        """When the clip has no leading handle (test default), the constant
        is still emitted (it's just zero).
        """
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
            # uses wrapper default src_start_frame=0
        )
        assert "local SRC_START_FRAME = 0" in script


# ---------------------------------------------------------------------------
# Diagnostics still emitted
# ---------------------------------------------------------------------------


class TestPerTrackDiagnostic:
    def test_first_keyframe_diagnostic_is_emitted(self):
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
        )
        assert "track 1 first kf:" in script
        assert "Center=" in script

    def test_calibration_block_is_removed(self):
        """The debug-only calibration markers should no longer appear in the
        production script.
        """
        script = _generate_lua_script_for_clip(
            "clipA", _single_box_detections(), frame_count=12,
        )
        assert "calib_top" not in script
        assert "calib_bot" not in script
        assert "calib_bar" not in script
        assert "Comp CurrentTime" not in script
        assert "local aspect = " not in script


# ---------------------------------------------------------------------------
# Track grouping
# ---------------------------------------------------------------------------


class TestGroupIntoTracks:
    def test_single_box_across_two_frames_is_one_track(self):
        detections = _single_box_detections()
        tracks = _group_into_tracks(detections)
        assert len(tracks) == 1
        assert sorted(tracks[0].keys()) == [10, 11]

    def test_two_boxes_far_apart_become_two_tracks(self):
        detections = _make_detections({
            0: {"x": 0.1, "y": 0.1, "w": 0.05, "h": 0.05},
            1: {"x": 0.8, "y": 0.8, "w": 0.05, "h": 0.05},
        })
        tracks = _group_into_tracks(detections)
        assert len(tracks) == 2


# ---------------------------------------------------------------------------
# Boundary keyframes (zero-size mask outside detection range)
# ---------------------------------------------------------------------------


class TestBoundaryKeyframes:
    """Fusion holds the first/last keyframe value for all frames outside the
    keyframe range.  Zero-size boundary keyframes at first_kf-1 and last_kf+1
    prevent blur from appearing on undetected frames.
    """

    def test_pre_boundary_keyframe_when_detections_start_mid_clip(self):
        """When detections start at frame 50, a zero-size keyframe is inserted
        at frame 49 for Width, Height, and XBlurSize."""
        detections = _make_detections({
            50: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
            51: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
        })
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=100,
        )
        # Pre-boundary at frame 47 (first_kf=48 due to ±2 window, so 48-1=47)
        width_lines = _find_keyframe_lines(script, "Width")
        width_by_frame = {
            _parse_keyframe_frame(ln): _parse_scalar_rhs(ln) for ln in width_lines
        }
        assert 47 in width_by_frame
        assert width_by_frame[47] == 0

        height_lines = _find_keyframe_lines(script, "Height")
        height_by_frame = {
            _parse_keyframe_frame(ln): _parse_scalar_rhs(ln) for ln in height_lines
        }
        assert 47 in height_by_frame
        assert height_by_frame[47] == 0

    def test_post_boundary_keyframe_when_detections_end_before_clip_end(self):
        """When detections end at frame 51, a zero-size keyframe is inserted
        after the last keyframed frame."""
        detections = _make_detections({
            50: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
            51: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
        })
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=100,
        )
        # Last kf is at 53 (51+2 window), post-boundary at 54
        width_lines = _find_keyframe_lines(script, "Width")
        width_by_frame = {
            _parse_keyframe_frame(ln): _parse_scalar_rhs(ln) for ln in width_lines
        }
        assert 54 in width_by_frame
        assert width_by_frame[54] == 0

    def test_no_pre_boundary_when_detections_start_at_frame_0(self):
        """When detections start at frame 0, no pre-boundary keyframe is needed."""
        detections = _make_detections({
            0: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
            1: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
        })
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=10,
        )
        width_lines = _find_keyframe_lines(script, "Width")
        frames = sorted(_parse_keyframe_frame(ln) for ln in width_lines)
        # No frame before 0 should exist
        assert all(f >= 0 for f in frames)
        # Frame 0 should be the actual detection (not zero)
        width_by_frame = {
            _parse_keyframe_frame(ln): _parse_scalar_rhs(ln) for ln in width_lines
        }
        assert width_by_frame[0] == 0.2

    def test_no_post_boundary_when_detections_end_at_last_frame(self):
        """When detections end at the last frame, no post-boundary is needed."""
        detections = _make_detections({
            8: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
            9: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
        })
        # frame_count=10, last detection at 9, nearest window gives kf at 9
        # 9+1=10 >= frame_count=10, so no post-boundary
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=10,
        )
        width_lines = _find_keyframe_lines(script, "Width")
        frames = sorted(_parse_keyframe_frame(ln) for ln in width_lines)
        # No frame >= frame_count should exist
        assert all(f < 10 for f in frames)

    def test_blur_size_also_gets_boundary_keyframes(self):
        """XBlurSize spline also gets zero-size boundary keyframes."""
        detections = _make_detections({
            50: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
            51: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
        })
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=100,
        )
        blur_lines = _find_keyframe_lines(script, "XBlurSize", mask_var="blur1")
        blur_by_frame = {
            _parse_keyframe_frame(ln): _parse_scalar_rhs(ln) for ln in blur_lines
        }
        # Pre-boundary at 47 and post-boundary at 54
        assert 47 in blur_by_frame
        assert blur_by_frame[47] == 0
        assert 54 in blur_by_frame
        assert blur_by_frame[54] == 0


class TestEmptyDetections:
    def test_empty_detections_yield_empty_script(self):
        assert _generate_lua_script_for_clip("clipA", {}, frame_count=10) == ""


# ---------------------------------------------------------------------------
# Relative blur sizing
# ---------------------------------------------------------------------------


class TestRelativeBlurSize:
    """XBlurSize is auto-scaled by relative plate area within the clip:
    smallest plate -> _BLUR_SIZE_MIN, largest -> _BLUR_SIZE_MAX.
    """

    def test_single_plate_constant_size_gets_blur_min(self):
        """One plate with the same size on every frame -> all XBlurSize = 1.0."""
        detections = _make_detections({
            0: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
            1: {"x": 0.4, "y": 0.45, "w": 0.2, "h": 0.05},
        })
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=2,
        )
        blur_lines = _find_keyframe_lines(script, "XBlurSize", mask_var="blur1")
        assert blur_lines, f"no XBlurSize lines:\n{script}"
        for line in blur_lines:
            assert _parse_scalar_rhs(line) == _BLUR_SIZE_MIN

    def test_two_tracks_different_areas_get_min_max(self):
        """Small plate -> 1.0, large plate -> 2.0."""
        # Two spatially separated plates at the same frame with different sizes.
        # _group_into_tracks splits them because centers are far apart.
        detections = {
            "0": [
                {"x": 0.05, "y": 0.05, "w": 0.05, "h": 0.05},
                {"x": 0.80, "y": 0.80, "w": 0.10, "h": 0.10},
            ],
        }
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=1,
        )
        # Small plate: area = 0.05*0.05 = 0.0025 -> blur_min
        blur1_lines = _find_keyframe_lines(script, "XBlurSize", mask_var="blur1")
        # Large plate: area = 0.10*0.10 = 0.01 -> blur_max
        blur2_lines = _find_keyframe_lines(script, "XBlurSize", mask_var="blur2")
        assert blur1_lines and blur2_lines
        small_val = _parse_scalar_rhs(blur1_lines[0])
        large_val = _parse_scalar_rhs(blur2_lines[0])
        assert {small_val, large_val} == {_BLUR_SIZE_MIN, _BLUR_SIZE_MAX}

    def test_intermediate_area_gets_interpolated_value(self):
        """Three plates with areas in ratio 1:2:4 get correctly interpolated."""
        detections = {
            "0": [
                # Small: area = 0.04*0.04 = 0.0016
                {"x": 0.05, "y": 0.05, "w": 0.04, "h": 0.04},
                # Medium: area = 0.04*0.08 = 0.0032 (midpoint)
                {"x": 0.40, "y": 0.40, "w": 0.04, "h": 0.08},
                # Large: area = 0.08*0.06 = 0.0048
                {"x": 0.80, "y": 0.80, "w": 0.08, "h": 0.06},
            ],
        }
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=1,
        )
        blur1 = _parse_scalar_rhs(
            _find_keyframe_lines(script, "XBlurSize", mask_var="blur1")[0]
        )
        blur2 = _parse_scalar_rhs(
            _find_keyframe_lines(script, "XBlurSize", mask_var="blur2")[0]
        )
        blur3 = _parse_scalar_rhs(
            _find_keyframe_lines(script, "XBlurSize", mask_var="blur3")[0]
        )
        vals = sorted([blur1, blur2, blur3])
        assert vals[0] == _BLUR_SIZE_MIN
        assert vals[2] == _BLUR_SIZE_MAX
        # Midpoint: (0.0032 - 0.0016) / (0.0048 - 0.0016) = 0.5
        assert abs(vals[1] - 1.5) < 1e-9

    def test_plate_changing_size_across_frames(self):
        """One track whose plate grows: min frame -> 1.0, max frame -> 2.0."""
        detections = _make_detections({
            0: {"x": 0.4, "y": 0.4, "w": 0.05, "h": 0.05},  # area = 0.0025
            1: {"x": 0.4, "y": 0.4, "w": 0.10, "h": 0.10},  # area = 0.01
        })
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=2,
        )
        blur_lines = _find_keyframe_lines(script, "XBlurSize", mask_var="blur1")
        vals_by_frame = {
            _parse_keyframe_frame(ln): _parse_scalar_rhs(ln)
            for ln in blur_lines
        }
        assert vals_by_frame[0] == _BLUR_SIZE_MIN
        assert vals_by_frame[1] == _BLUR_SIZE_MAX

    def test_all_identical_areas_get_blur_min(self):
        """Degenerate case: all plates same area -> no division by zero, all 1.0."""
        detections = {
            "0": [
                {"x": 0.1, "y": 0.1, "w": 0.05, "h": 0.05},
                {"x": 0.8, "y": 0.8, "w": 0.05, "h": 0.05},
            ],
        }
        script = _generate_lua_script_for_clip(
            "clipA", detections, frame_count=1,
        )
        blur1 = _find_keyframe_lines(script, "XBlurSize", mask_var="blur1")
        blur2 = _find_keyframe_lines(script, "XBlurSize", mask_var="blur2")
        for line in blur1 + blur2:
            assert _parse_scalar_rhs(line) == _BLUR_SIZE_MIN

    def test_compute_blur_sizes_empty_tracks(self):
        """Empty tracks produce empty result."""
        assert _compute_blur_sizes([], frame_count=10) == {}
        assert _compute_blur_sizes([{}], frame_count=5) == {}
