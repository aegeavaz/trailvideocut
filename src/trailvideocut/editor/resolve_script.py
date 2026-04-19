"""Generate DaVinci Resolve companion files for plate blur.

Supports two modes:
- Fusion .comp files (works with Resolve Free) — one per clip
- Automation script + WSL interop (requires Resolve Studio)
"""

from __future__ import annotations

import glob
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fusion .comp file generation (Resolve Free compatible)
# ---------------------------------------------------------------------------

# Maximum distance (in frames) to search for a nearby detection when
# densifying keyframes for a comp frame that has no exact detection.
# Mirrors the +/-1 tolerance MoviePy's expand_boxes_for_drift uses, but a
# touch wider so an isolated dropped frame in detection still gets a value.
_NEAREST_WINDOW = 2

# XBlurSize range for relative plate area scaling.
# Smallest plate in a clip -> _BLUR_SIZE_MIN, largest -> _BLUR_SIZE_MAX.
# The floor was raised from 1.0 to 1.5 because at 1.0 the smallest plates
# remained legible after the Fusion blur was applied; the dynamic range (1.0)
# is unchanged. The in-Resolve embedded Python body in `_SCRIPT_TEMPLATE` must
# be kept in sync (a dedicated test enforces this).
_BLUR_SIZE_MIN = 1.5
_BLUR_SIZE_MAX = 2.5


def _nearest_box_for_frame(
    track: dict[int, dict],
    frame: int,
    window: int = _NEAREST_WINDOW,
) -> dict | None:
    """Return the box from *track* whose frame is closest to *frame*.

    Searches up to *window* frames in either direction; ties prefer the
    earlier frame.  Returns ``None`` if no detection lies within the window.
    """
    box = track.get(frame)
    if box is not None:
        return box
    for offset in range(1, window + 1):
        # Prefer earlier frame on ties (offset before -offset).
        prev = track.get(frame - offset)
        if prev is not None:
            return prev
        nxt = track.get(frame + offset)
        if nxt is not None:
            return nxt
    return None


def _compute_blur_sizes(
    tracks: list[dict[int, dict]],
    frame_count: int,
) -> dict[tuple[int, int], float]:
    """Compute per-(track_index, frame) XBlurSize using relative plate area.

    The smallest plate bounding-box area across all tracks and frames in the
    clip gets ``_BLUR_SIZE_MIN``, the largest gets ``_BLUR_SIZE_MAX``, with
    linear interpolation for intermediate sizes.

    Returns a mapping of ``(track_index, clip_relative_frame) -> blur_size``.
    """
    entries: list[tuple[int, int, float]] = []  # (ti, frame, area)
    for ti, track in enumerate(tracks):
        for f in range(frame_count):
            box = _nearest_box_for_frame(track, f, _NEAREST_WINDOW)
            if box is None:
                continue
            area = box["w"] * box["h"]
            entries.append((ti, f, area))

    if not entries:
        return {}

    areas = [a for _, _, a in entries]
    min_area = min(areas)
    max_area = max(areas)
    span = max_area - min_area

    result: dict[tuple[int, int], float] = {}
    for ti, f, area in entries:
        if span > 0:
            t = (area - min_area) / span
            result[(ti, f)] = _BLUR_SIZE_MIN + t * (_BLUR_SIZE_MAX - _BLUR_SIZE_MIN)
        else:
            result[(ti, f)] = _BLUR_SIZE_MIN
    return result


def _generate_lua_script_for_clip(
    clip_name: str,
    detections: dict[str, list[dict]],
    frame_count: int,
    src_start_frame: int,
) -> str:
    """Generate a Fusion Lua script that adds blur nodes to the current comp.

    The script runs inside Fusion's console (Workspace > Console) and works
    with Resolve Free.  It operates on the existing composition where
    MediaIn1 is already connected to the timeline clip's media.

    *frame_count* is the number of clip-relative frames to densify keyframes
    over (i.e. the clip's source duration in frames).

    *src_start_frame* is the absolute source-video frame number that
    corresponds to the clip's first frame (clip-relative frame 0).  At
    runtime, the script reads MediaIn1.ClipTimeStart (= the comp time at
    which media frame 0 is positioned) and computes the comp frame for
    each plate via:

        clip_first_visible_comp_frame = src_start_frame + ClipTimeStart
        comp_frame_for_rel(rel) = clip_first_visible_comp_frame + rel

    This corrects for crossfade leading/trailing handle frames that
    Resolve adds to the Fusion comp around the actual clip content.
    """
    tracks = _group_into_tracks(detections)
    if not tracks:
        return ""

    blur_sizes = _compute_blur_sizes(tracks, frame_count)

    lines = [
        f"-- TrailVideoCut plate blur for clip: {clip_name}",
        "-- Run in Fusion console: Workspace > Console, then paste or dofile()",
        "",
        "local comp = fu:GetCurrentComp()",
        "if not comp then print('ERROR: No active composition') return end",
        "",
        "comp:StartUndo('TrailVideoCut Plate Blur')",
        "",
        "local media_in = comp:FindTool('MediaIn1')",
        "local media_out = comp:FindTool('MediaOut1')",
        "if not media_in then print('ERROR: MediaIn1 not found') return end",
        "if not media_out then print('ERROR: MediaOut1 not found') return end",
        "",
        "-- Comp frame range (for diagnostic only)",
        "local attrs = comp:GetAttrs()",
        "local render_start = attrs.COMPN_RenderStart or 0",
        "local render_end = attrs.COMPN_RenderEnd or 0",
        "print('Comp render range: ' .. render_start .. ' - ' .. render_end)",
        "",
        "-- Map clip-relative plate frames to COMP frames.",
        "-- MediaIn1.ClipTimeStart tells us at which comp time the source",
        "-- video's frame 0 is positioned.  For a clip whose first source",
        "-- frame is SRC_START_FRAME, the first visible comp frame is at",
        "-- SRC_START_FRAME + ClipTimeStart.  This compensates for leading",
        "-- handle frames Resolve adds for crossfade transitions.",
        "--",
        "-- DIAGNOSTIC ESCAPE HATCH (intentionally kept, not dead code):",
        "-- If KEYFRAME_OFFSET_OVERRIDE is non-nil, that value is used directly",
        "-- as clip_offset, ignoring ClipTimeStart and the PTS gap correction.",
        "-- Use this to test different offsets manually if the auto-computed",
        "-- value doesn't track the plate correctly.  Try 0, 1, 2, 3, or -1.",
        "local KEYFRAME_OFFSET_OVERRIDE = nil  -- set to a number to override",
        "",
        f"local SRC_START_FRAME = {src_start_frame}",
        "local mi_clip_start = media_in:GetInput('ClipTimeStart')",
        "if mi_clip_start == nil then mi_clip_start = 0 end",
        "local clip_offset",
        "if KEYFRAME_OFFSET_OVERRIDE ~= nil then",
        "  clip_offset = KEYFRAME_OFFSET_OVERRIDE",
        "  print('USING KEYFRAME_OFFSET_OVERRIDE = ' .. clip_offset)",
        "else",
        "  clip_offset = SRC_START_FRAME + mi_clip_start",
        "  print('SRC_START_FRAME=' .. SRC_START_FRAME ..",
        "        ' MediaIn1.ClipTimeStart=' .. mi_clip_start ..",
        "        ' -> clip_offset=' .. clip_offset)",
        "end",
        "",
        "-- Helper: compute the comp frame for a clip-relative frame.",
        "local function comp_for_rel(rel)",
        "  return clip_offset + rel",
        "end",
        "",
        "-- Get frame dimensions (diagnostic only)",
        "local mi_attrs = media_in:GetAttrs()",
        "local frame_w = mi_attrs.TOOLIT_Clip_Width and mi_attrs.TOOLIT_Clip_Width[1] or 1920",
        "local frame_h = mi_attrs.TOOLIT_Clip_Height and mi_attrs.TOOLIT_Clip_Height[1] or 1080",
        "print('Frame size: ' .. frame_w .. 'x' .. frame_h)",
        "",
        "local prev_output = media_in",
    ]

    for ti, track in enumerate(tracks):
        blur_var = f"blur{ti + 1}"
        mask_var = f"mask{ti + 1}"

        lines.append(f"")
        lines.append(f"-- Plate track {ti + 1}")
        lines.append(f"local {mask_var} = comp:AddTool('RectangleMask', -32768, -32768)")
        lines.append(f"local {blur_var} = comp:AddTool('Blur', -32768, -32768)")
        lines.append(f"")

        # Connect blur input to previous output in the chain
        lines.append(f"{blur_var}:SetInput('Input', prev_output.Output)")
        # Connect mask to blur's effect mask
        lines.append(f"{blur_var}:SetInput('EffectMask', {mask_var}.Mask)")
        lines.append(f"")

        # Build a DENSE per-comp-frame keyframe list, one entry per frame in
        # [0, frame_count).  For frames where the track has no detection,
        # use the nearest detection within +/- _NEAREST_WINDOW frames; if
        # nothing is in range, skip that frame (no keyframe).
        #
        # Densifying defeats Fusion's bezier interpolation between sparse
        # keyframes (which was causing visible drift on moving plates) and
        # makes the script tolerant to small +/-1 frame seek mismatches in
        # Resolve, since adjacent comp frames have valid keyframes.
        #
        # Fusion's RectangleMask uses image-relative coordinates:
        #   Center.X: 0.0 left  -> 1.0 right    (image-width-relative)
        #   Center.Y: 0.0 BOTTOM -> 1.0 TOP     (image-height-relative, Y-UP)
        #   Width:    image-width-relative  (Width = 1.0 = full image width)
        #   Height:   image-height-relative (Height = 1.0 = full image height)
        # PlateBox stores Y top-down, so we invert Y for Fusion.
        kf_data: list[tuple[int, float, float, float, float]] = []
        # (frame, cx, cy, w, h)
        for f in range(frame_count):
            box = _nearest_box_for_frame(track, f, _NEAREST_WINDOW)
            if box is None:
                continue
            cx = box["x"] + box["w"] / 2
            cy = 1.0 - (box["y"] + box["h"] / 2)
            kf_data.append((f, cx, cy, box["w"], box["h"]))

        # Compute boundary frames for zero-size keyframes.
        # Fusion holds the first/last keyframe value for all frames outside
        # the keyframe range.  Inserting zero-size keyframes one frame before
        # the first detection and one frame after the last detection prevents
        # blur from appearing on frames where no plate was detected.
        first_kf_frame = kf_data[0][0] if kf_data else 0
        last_kf_frame = kf_data[-1][0] if kf_data else 0

        # Per-track diagnostic: print the first keyframe so the user can
        # cross-check Center / sizes against the preview overlay at runtime.
        if kf_data:
            first_f, first_cx, first_cy, first_w, first_h = kf_data[0]
            lines.append(
                f"print(string.format('  track {ti + 1} first kf: frame %d "
                f"Center={{%.4f, %.4f}} Width=%.4f Height=%.4f', "
                f"comp_for_rel({first_f}), {first_cx}, {first_cy}, "
                f"{first_w}, {first_h}))"
            )

        # Assign animated splines to inputs then set keyframes.
        # Frame positions use comp_for_rel() which applies the piecewise
        # PTS-gap correction when needed.
        lines.append(f"-- Animate mask center")
        lines.append(f"{mask_var}.Center = XYPath({{}})")
        if first_kf_frame > 0:
            lines.append(f"{mask_var}.Center[comp_for_rel({first_kf_frame - 1})] = {{0.5, 0.5}}")
        for frame, cx, cy, _w, _h in kf_data:
            lines.append(f"{mask_var}.Center[comp_for_rel({frame})] = {{{cx}, {cy}}}")
        if last_kf_frame + 1 < frame_count:
            lines.append(f"{mask_var}.Center[comp_for_rel({last_kf_frame + 1})] = {{0.5, 0.5}}")

        lines.append(f"-- Animate mask width")
        lines.append(f"{mask_var}.Width = BezierSpline({{}})")
        if first_kf_frame > 0:
            lines.append(f"{mask_var}.Width[comp_for_rel({first_kf_frame - 1})] = 0")
        for frame, _cx, _cy, w, _h in kf_data:
            lines.append(f"{mask_var}.Width[comp_for_rel({frame})] = {w}")
        if last_kf_frame + 1 < frame_count:
            lines.append(f"{mask_var}.Width[comp_for_rel({last_kf_frame + 1})] = 0")

        lines.append(f"-- Animate mask height")
        lines.append(f"{mask_var}.Height = BezierSpline({{}})")
        if first_kf_frame > 0:
            lines.append(f"{mask_var}.Height[comp_for_rel({first_kf_frame - 1})] = 0")
        for frame, _cx, _cy, _w, h in kf_data:
            lines.append(f"{mask_var}.Height[comp_for_rel({frame})] = {h}")
        if last_kf_frame + 1 < frame_count:
            lines.append(f"{mask_var}.Height[comp_for_rel({last_kf_frame + 1})] = 0")

        # Readback diagnostic for the first track only.
        if ti == 0 and kf_data:
            first_f, _, _, _, _ = kf_data[0]
            lines.append(
                f"local rb_frame = comp_for_rel({first_f})"
            )
            lines.append(
                f"local rb_center = {mask_var}:GetInput('Center', rb_frame)"
            )
            lines.append(
                f"local rb_width = {mask_var}:GetInput('Width', rb_frame)"
            )
            lines.append(
                f"local rb_height = {mask_var}:GetInput('Height', rb_frame)"
            )
            lines.append(
                "if rb_center then "
                "print(string.format('  readback @ frame %d: Center={%.4f, %.4f} "
                "Width=%.4f Height=%.4f', "
                "rb_frame, rb_center[1] or -1, rb_center[2] or -1, "
                "rb_width or -1, rb_height or -1)) "
                "else print('  readback @ frame ' .. rb_frame .. ': nil (no value at this frame!)') end"
            )

        # Blur size: auto-scaled by relative plate area within the clip
        lines.append(f"-- Animate blur size (auto-scaled by relative plate area)")
        lines.append(f"{blur_var}.XBlurSize = BezierSpline({{}})")
        if first_kf_frame > 0:
            lines.append(f"{blur_var}.XBlurSize[comp_for_rel({first_kf_frame - 1})] = 0")
        for frame, _cx, _cy, _w, _h in kf_data:
            bs = blur_sizes.get((ti, frame), _BLUR_SIZE_MIN)
            lines.append(
                f"{blur_var}.XBlurSize[comp_for_rel({frame})] = {bs}"
            )
        if last_kf_frame + 1 < frame_count:
            lines.append(f"{blur_var}.XBlurSize[comp_for_rel({last_kf_frame + 1})] = 0")

        lines.append(f"prev_output = {blur_var}")

    # Connect last blur to MediaOut
    lines.append("")
    lines.append("-- Connect last blur to MediaOut")
    lines.append("media_out:SetInput('Input', prev_output.Output)")
    lines.append("")
    lines.append("comp:EndUndo(true)")
    lines.append(f"print('TrailVideoCut: Applied blur to {clip_name} "
                 f"({len(tracks)} plate(s))')")

    return "\n".join(lines) + "\n"


def _group_into_tracks(
    detections: dict[str, list[dict]],
    max_dist: float = 0.1,
) -> list[dict[int, dict]]:
    """Group per-frame plate boxes into spatial tracks.

    Each track maps frame_num -> box_dict for one physical plate across time.
    """
    tracks: list[dict[int, dict]] = []

    for frame_str in sorted(detections.keys(), key=int):
        frame_num = int(frame_str)
        boxes = detections[frame_str]

        used_tracks: set[int] = set()
        for box in boxes:
            cx = box["x"] + box["w"] / 2
            cy = box["y"] + box["h"] / 2

            best_track = None
            best_dist = max_dist

            for ti, track in enumerate(tracks):
                if ti in used_tracks:
                    continue
                last_frame = max(track.keys())
                last_box = track[last_frame]
                lcx = last_box["x"] + last_box["w"] / 2
                lcy = last_box["y"] + last_box["h"] / 2
                dist = ((cx - lcx) ** 2 + (cy - lcy) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_track = ti

            if best_track is not None:
                tracks[best_track][frame_num] = box
                used_tracks.add(best_track)
            else:
                tracks.append({frame_num: box})

    return tracks


def generate_fusion_scripts(
    plate_clips: list[tuple[str, dict[str, list[dict]], float, int, int]],
    output_dir: Path,
) -> list[Path]:
    """Generate Fusion Lua scripts for clips with plate data.

    Each script runs inside Fusion's console (Workspace > Console)
    and works with Resolve Free.

    Parameters
    ----------
    plate_clips : list of (clip_name, detections, fps, frame_count, src_start_frame)
        - src_start_frame is the absolute source-video frame number that
          the clip's source_range starts at.
    output_dir : Path to write .lua files

    Returns list of generated .lua file paths.
    """
    paths = []
    for clip_name, detections, _fps, frame_count, src_start_frame in plate_clips:
        content = _generate_lua_script_for_clip(
            clip_name, detections, frame_count, src_start_frame,
        )
        if not content:
            continue
        lua_path = output_dir / f"{clip_name}_blur.lua"
        lua_path.write_text(content, encoding="utf-8")
        paths.append(lua_path)
    return paths

_SCRIPT_TEMPLATE = r'''#!/usr/bin/env python3
"""
TrailVideoCut — Apply plate blur to DaVinci Resolve timeline.

Generated automatically. Requirements:
  - DaVinci Resolve Studio 20+ running with external scripting enabled
    (Preferences > System > General > External scripting using: Local)
  - opentimelineio Python package (pip install opentimelineio)

Usage:
  python {script_name} [--otio-path PATH] [--dry-run]
"""

import argparse
import json
import os
import subprocess
import sys

# Flush prints immediately so output isn't lost on crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
else:
    import functools
    print = functools.partial(print, flush=True)  # noqa: A001

OTIO_PATH = r"{otio_path}"
SOURCE_FPS = {fps}


# ---------------------------------------------------------------------------
# Resolve connection
# ---------------------------------------------------------------------------

def _resolve_script_dirs():
    """Return candidate directories for the DaVinciResolveScript module."""
    dirs = []
    env_api = os.environ.get("RESOLVE_SCRIPT_API")
    if env_api:
        dirs.append(os.path.join(env_api, "Modules"))
    dirs.append(os.path.join(
        os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
        "Blackmagic Design", "DaVinci Resolve", "Support",
        "Developer", "Scripting", "Modules",
    ))
    return dirs


def _check_resolve_reachable():
    """Quick pre-flight: verify fusionscript loads without crashing.

    Runs a tiny subprocess that just imports the module and calls
    scriptapp.  If that subprocess crashes (access violation when
    Resolve is not running), we catch it here instead of crashing
    the main script.

    Returns (ok, error_message).
    """
    # Build a one-liner that tries to connect
    dirs = _resolve_script_dirs()
    setup_lines = "; ".join(
        f"__import__('sys').path.insert(0, r'{{d}}')"
        for d in dirs if os.path.isdir(d)
    )
    probe = (
        f"{{setup_lines}}; "
        "dvr = __import__('DaVinciResolveScript'); "
        "r = dvr.scriptapp('Resolve'); "
        "print('OK' if r else 'NO_RESOLVE')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=15,
        )
        stdout = result.stdout.strip()
        if result.returncode != 0:
            code = result.returncode
            # 0xC0000005 = access violation (Resolve not running)
            if code < 0 or code == 3221225477:
                return False, (
                    "fusionscript crashed (Resolve likely not running). "
                    "Start DaVinci Resolve Studio and enable external scripting "
                    "(Preferences > System > General > External scripting using: Local)."
                )
            return False, (
                f"DaVinciResolveScript probe failed (exit {{code}}): "
                f"{{result.stderr.strip()[:200]}}"
            )
        if "NO_RESOLVE" in stdout:
            return False, (
                "Could not connect to DaVinci Resolve. "
                "Make sure Resolve Studio is running and external scripting "
                "is enabled (Preferences > System > General)."
            )
        if "OK" in stdout:
            return True, ""
        return False, f"Unexpected probe output: {{stdout[:200]}}"
    except FileNotFoundError:
        return False, "Python interpreter not found for probe."
    except subprocess.TimeoutExpired:
        return False, "Resolve connection probe timed out."


def _find_resolve_script_module():
    """Locate and import DaVinciResolveScript."""
    for path in _resolve_script_dirs():
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

    try:
        import DaVinciResolveScript as dvr  # type: ignore[import-untyped]
        return dvr
    except ImportError:
        return None


def connect_resolve():
    """Connect to a running DaVinci Resolve instance.

    Returns (resolve_object, error_message).
    """
    # Pre-flight check in a subprocess to avoid crashing this process
    ok, err = _check_resolve_reachable()
    if not ok:
        return None, err

    dvr = _find_resolve_script_module()
    if dvr is None:
        return None, (
            "DaVinciResolveScript module not found. "
            "Ensure DaVinci Resolve Studio is installed and "
            "RESOLVE_SCRIPT_API is set."
        )
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        return None, (
            "Could not connect to DaVinci Resolve. "
            "Make sure Resolve Studio is running and external scripting "
            "is enabled (Preferences > System > General)."
        )
    return resolve, None


# ---------------------------------------------------------------------------
# OTIO plate metadata loading
# ---------------------------------------------------------------------------

def load_plate_metadata(otio_path):
    """Load plate metadata from OTIO clip metadata.

    Returns list of (clip_name, detections_dict, fps).
    """
    try:
        import opentimelineio as otio
    except ImportError:
        print("ERROR: opentimelineio not installed. pip install opentimelineio")
        return []

    timeline = otio.adapters.read_from_file(otio_path)
    results = []
    for track in timeline.tracks:
        if track.kind != otio.schema.TrackKind.Video:
            continue
        for item in track:
            if not isinstance(item, otio.schema.Clip):
                continue
            tv_meta = item.metadata.get("trailvideocut")
            if not tv_meta:
                continue
            plates = tv_meta.get("plates")
            if not plates or not plates.get("detections"):
                continue
            results.append((
                item.name,
                plates["detections"],
                plates.get("fps", SOURCE_FPS),
            ))
    return results


# ---------------------------------------------------------------------------
# Plate track grouping
# ---------------------------------------------------------------------------

def group_into_tracks(detections, max_dist=0.1):
    """Group per-frame plate boxes into spatial tracks.

    Each track is a dict mapping frame_num -> box_dict for one
    physical plate across time.  Boxes are matched across frames
    by nearest-center distance.
    """
    tracks = []  # list of dict[int, box_dict]

    for frame_str in sorted(detections.keys(), key=int):
        frame_num = int(frame_str)
        boxes = detections[frame_str]

        used_tracks = set()
        for box in boxes:
            cx = box["x"] + box["w"] / 2
            cy = box["y"] + box["h"] / 2

            best_track = None
            best_dist = max_dist

            for ti, track in enumerate(tracks):
                if ti in used_tracks:
                    continue
                # Compare with most recent frame in this track
                last_frame = max(track.keys())
                last_box = track[last_frame]
                lcx = last_box["x"] + last_box["w"] / 2
                lcy = last_box["y"] + last_box["h"] / 2
                dist = ((cx - lcx) ** 2 + (cy - lcy) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_track = ti

            if best_track is not None:
                tracks[best_track][frame_num] = box
                used_tracks.add(best_track)
            else:
                tracks.append({{frame_num: box}})

    return tracks


# ---------------------------------------------------------------------------
# Fusion composition creation
# ---------------------------------------------------------------------------

# Maximum distance (in frames) for the nearest-neighbor lookup that fills
# in dense per-comp-frame keyframes between sparse detections.  Mirrors the
# Lua generator's _NEAREST_WINDOW.
NEAREST_WINDOW = 2


def _nearest_box(track, frame, window=NEAREST_WINDOW):
    """Return the box from *track* whose frame is closest to *frame*, or None.

    Searches up to *window* frames in either direction; ties prefer the
    earlier frame.
    """
    box = track.get(frame)
    if box is not None:
        return box
    for offset in range(1, window + 1):
        prev = track.get(frame - offset)
        if prev is not None:
            return prev
        nxt = track.get(frame + offset)
        if nxt is not None:
            return nxt
    return None


def apply_blur_to_clip(comp, tracks, frame_width, frame_height):
    """Add Fusion Blur + RectangleMask nodes for each plate track.

    Parameters
    ----------
    comp : Fusion Composition object
    tracks : list of dict[int, box_dict]
    frame_width, frame_height : int
        Timeline resolution (kept for signature compatibility).

    Keyframes are densified: one keyframe per comp frame within +/- 2 frames
    of any detection in the track, eliminating Bezier interpolation drift.
    XBlurSize is auto-scaled by relative plate area: smallest plate -> 1.5,
    largest -> 2.5.  Must stay in sync with `_BLUR_SIZE_MIN` / `_BLUR_SIZE_MAX`
    in the host module.
    """
    if not tracks:
        return 0

    # Compute global min/max plate area across all tracks for blur scaling
    all_areas = []
    for _track in tracks:
        for _box in _track.values():
            all_areas.append(_box["w"] * _box["h"])
    min_area = min(all_areas) if all_areas else 0
    max_area = max(all_areas) if all_areas else 0
    area_span = max_area - min_area

    applied = 0

    for track_idx, track in enumerate(tracks):
        if not track:
            continue

        blur = comp.AddTool("Blur", -32768, -32768)
        mask = comp.AddTool("RectangleMask", -32768, -32768)

        if blur is None or mask is None:
            print(f"  WARNING: Could not create Fusion tools for track {{track_idx}}")
            continue

        # Connect mask to blur's effect mask
        blur.EffectMask = mask.Output

        # Connect blur into the pipeline
        media_in = comp.FindTool("MediaIn1")
        media_out = comp.FindTool("MediaOut1")

        if applied == 0 and media_in and media_out:
            # First blur: insert between MediaIn and MediaOut
            blur.Input = media_in.Output
            media_out.Input = blur.Output
        elif applied > 0:
            # Chain: previous blur's output -> this blur's input
            # MediaOut already points to previous blur
            prev_output = media_out.Input  # Save current connection
            blur.Input = prev_output
            media_out.Input = blur.Output

        # Densify: write a keyframe at every comp frame in the range
        # [min(track) - window, max(track) + window], using the nearest
        # detection within the window for frames that have no exact match.
        track_frames = sorted(track.keys())
        start_f = max(0, track_frames[0] - NEAREST_WINDOW)
        end_f = track_frames[-1] + NEAREST_WINDOW + 1

        for frame_num in range(start_f, end_f):
            box = _nearest_box(track, frame_num)
            if box is None:
                continue

            # Fusion's RectangleMask uses image-relative coordinates with
            # Y-UP origin (0=bottom, 1=top); PlateBox uses Y-down so we
            # invert.  Width/Height are independent image-relative
            # fractions, same as PlateBox, so passed through directly.
            center_x = box["x"] + box["w"] / 2
            center_y = 1.0 - (box["y"] + box["h"] / 2)
            width = box["w"]
            height = box["h"]

            # Auto-scaled blur size: smallest plate area -> 1.5, largest -> 2.5
            box_area = box["w"] * box["h"]
            if area_span > 0:
                blur_size = 1.5 + (box_area - min_area) / area_span
            else:
                blur_size = 1.5

            mask.SetInput("Center", {{1: center_x, 2: center_y}}, frame_num)
            mask.SetInput("Width", width, frame_num)
            mask.SetInput("Height", height, frame_num)
            blur.SetInput("XBlurSize", blur_size, frame_num)

        applied += 1

    return applied


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Apply TrailVideoCut plate blur to DaVinci Resolve timeline",
    )
    parser.add_argument(
        "--otio-path", default=OTIO_PATH,
        help="Path to the OTIO file (default: embedded path)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Load and validate data without connecting to Resolve",
    )
    args = parser.parse_args()

    otio_path = args.otio_path
    if not os.path.isfile(otio_path):
        print(f"ERROR: OTIO file not found: {{otio_path}}")
        sys.exit(1)

    print(f"Loading plate data from: {{otio_path}}")
    clip_plates = load_plate_metadata(otio_path)

    if not clip_plates:
        print("No plate blur data found in OTIO metadata.")
        sys.exit(0)

    print(f"Found plate data for {{len(clip_plates)}} clip(s)")

    if args.dry_run:
        for name, dets, fps in clip_plates:
            tracks = group_into_tracks(dets)
            total_frames = sum(len(t) for t in tracks)
            print(f"  {{name}}: {{len(tracks)}} plate(s), {{total_frames}} keyframes")
        print("Dry run complete.")
        sys.exit(0)

    # Connect to Resolve
    resolve, err = connect_resolve()
    if err:
        print(f"ERROR: {{err}}")
        sys.exit(1)

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("ERROR: No project open in DaVinci Resolve.")
        sys.exit(1)

    media_pool = project.GetMediaPool()

    # Import the OTIO timeline
    print("Importing OTIO timeline into Resolve...")
    new_timeline = media_pool.ImportTimelineFromFile(otio_path, {{}})
    if new_timeline is None:
        print("ERROR: Failed to import OTIO timeline.")
        print("Try importing the .otio file manually, then re-run this script.")
        sys.exit(1)

    # Get timeline resolution for blur scaling
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("ERROR: No active timeline after import.")
        sys.exit(1)

    frame_width = int(timeline.GetSetting("timelineResolutionWidth") or 1920)
    frame_height = int(timeline.GetSetting("timelineResolutionHeight") or 1080)

    # Get video track items
    items = timeline.GetItemListInTrack("video", 1)
    if not items:
        print("ERROR: No clips found on video track 1.")
        sys.exit(1)

    # Build a name -> plate_data lookup
    plate_lookup = {{name: (dets, fps) for name, dets, fps in clip_plates}}

    total_applied = 0
    for item in items:
        name = item.GetName()
        if name not in plate_lookup:
            continue

        dets, fps = plate_lookup[name]
        tracks = group_into_tracks(dets)

        if not tracks:
            continue

        print(f"  Applying blur to '{{name}}': {{len(tracks)}} plate(s)...")
        comp = item.AddFusionComp()
        if comp is None:
            print(f"  WARNING: Could not create Fusion composition for '{{name}}'")
            continue

        count = apply_blur_to_clip(comp, tracks, frame_width, frame_height)
        total_applied += count

    print(f"Done! Applied blur to {{total_applied}} plate region(s).")


if __name__ == "__main__":
    main()
'''


def _wsl_to_windows_path(path: Path) -> str:
    """Convert a WSL path to a Windows-native path.

    /mnt/c/Users/foo → C:\\Users\\foo
    Non-WSL paths are returned as-is.
    """
    abs_str = str(path.resolve())
    if abs_str.startswith("/mnt/") and len(abs_str) > 6 and abs_str[5].isalpha():
        drive = abs_str[5].upper()
        rest = abs_str[6:].replace("/", "\\")
        return f"{drive}:{rest}"
    return abs_str


def generate_resolve_script(otio_path: Path, fps: float) -> str:
    """Generate a self-contained Python script for applying plate blur in Resolve.

    The script reads plate metadata from the OTIO file and uses
    DaVinciResolveScript to create Fusion blur compositions.
    """
    win_otio_path = _wsl_to_windows_path(otio_path)
    script_name = otio_path.stem + "_resolve_plates.py"
    return _SCRIPT_TEMPLATE.format(
        script_name=script_name,
        otio_path=win_otio_path,
        fps=fps,
    )


def _is_wsl() -> bool:
    """Detect if running under WSL."""
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _find_windows_python() -> str | None:
    """Find a Windows-native Python interpreter accessible from WSL.

    Searches standard install locations and validates the candidate
    runs as a win32 process.
    """
    candidates: list[str] = []

    # Windows Store / winget Python (on WSL PATH via interop)
    for name in ("python3.exe", "python.exe"):
        try:
            result = subprocess.run(
                ["which", name], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                if path.startswith("/mnt/"):
                    candidates.append(path)
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Standard CPython installer locations
    for pattern in (
        "/mnt/c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe",
        "/mnt/c/Python3*/python.exe",
    ):
        candidates.extend(sorted(glob.glob(pattern), reverse=True))

    # Validate each candidate is actually Windows Python
    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "-c", "import sys; print(sys.platform)"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and "win32" in result.stdout:
                return candidate
        except (subprocess.TimeoutExpired, OSError):
            continue

    return None


def _find_python_for_resolve() -> tuple[str, str] | None:
    """Find a Python interpreter that can reach DaVinci Resolve's scripting API.

    On Windows: use sys.executable (we're already on the same machine).
    On WSL: find a Windows-native Python via interop.
    Returns (python_path, script_path_for_that_python) or None.
    """
    import sys as _sys

    if _sys.platform == "win32":
        return _sys.executable, "native"
    if _is_wsl():
        win_python = _find_windows_python()
        if win_python:
            return win_python, "wsl"
    return None


def try_execute_resolve_script(script_path: Path) -> tuple[bool, str]:
    """Attempt to execute the companion script to apply blur in Resolve.

    On Windows: runs the script directly (same machine as Resolve).
    On WSL: runs via Windows Python through WSL interop.
    Returns (success, message).
    """
    result_info = _find_python_for_resolve()
    if result_info is None:
        return False, (
            f"Could not find a Python interpreter that can reach Resolve. "
            f"Run the script manually: python {script_path.name}"
        )

    python_path, mode = result_info

    # On WSL, the script path must be converted to Windows format
    if mode == "wsl":
        effective_script_path = _wsl_to_windows_path(script_path)
    else:
        effective_script_path = str(script_path)

    try:
        result = subprocess.run(
            [python_path, effective_script_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        combined = f"{stdout}\n{stderr}".strip()

        if result.returncode == 0 and "Done!" in stdout:
            return True, stdout
        elif "Could not connect" in combined:
            return False, (
                "Resolve not running or scripting not enabled. "
                f"Script saved: {script_path.name}"
            )
        else:
            return False, (
                f"Script failed (exit code {result.returncode}):\n"
                f"{combined[:500]}"
            )
    except subprocess.TimeoutExpired:
        return False, (
            "Script timed out. Resolve may be busy. "
            f"Try running manually: python {script_path.name}"
        )
    except OSError as e:
        return False, f"Could not execute script: {e}"
