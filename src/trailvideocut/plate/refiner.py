"""Post-process refinement of placed plate boxes.

Given a single video frame and an existing :class:`PlateBox`, :func:`refine_box`
searches the ROI around the box for high-gradient structures that plausibly
represent a plate, and returns either a tighter axis-aligned rectangle, an
oriented rectangle (when rotation is confidently estimated), or the input box
unchanged when no candidate survives the filters.

Design goals (see ``openspec/changes/refine-plate-box-fit/design.md``):

* Pure function of its inputs — no global state, no randomness.
* OpenCV + NumPy only; no new third-party dependencies.
* Cheap enough to run off-thread per box.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np

from trailvideocut.plate.models import PlateBox

logger = logging.getLogger(__name__)

RefineMethod = Literal["aabb", "oriented", "unchanged"]


@dataclass(frozen=True)
class RefinerConfig:
    """Tunable thresholds for :func:`refine_box`."""

    # ROI padding as a multiplier of the input box's (w, h). Default is 0 —
    # the refiner searches strictly inside the user-placed box. Any positive
    # value pulls in surrounding bodywork (e.g. motorcycle fenders) that the
    # morph-close step then fuses with the plate into a single over-sized
    # blob, which gets rejected by the ``max_area_fraction`` cap.
    roi_padding: float = 0.0

    # Contour area filters, as fractions of the input box area. The upper
    # bound is 1.0 by default — the user has already placed the box roughly
    # around the plate, so refinement can only **shrink** it. Allowing growth
    # tends to pull in adjacent dark bodywork that shares edges with the
    # plate and wins on edge-density scoring.
    min_area_fraction: float = 0.15
    max_area_fraction: float = 1.0

    # Aspect ratio bounds (long_side / short_side) for plate-like contours.
    # Default bounds cover both European car plates (~4.6:1) and square-ish
    # motorcycle / JP plates (~1.1:1 two-row layout). Tighten if false
    # positives become an issue on a specific dataset.
    min_aspect_ratio: float = 1.0
    max_aspect_ratio: float = 7.0

    # Maximum distance from a candidate's centre to the input box's centre,
    # expressed as a fraction of the input box's max(w, h).
    max_centre_distance: float = 0.6

    # Oriented output gate: absolute rotation must be at least this many
    # degrees AND the oriented score must beat the best AABB score by any
    # positive margin.
    min_oriented_angle_deg: float = 2.0

    # Confidence floor below which a RefinementResult is flagged low-confidence
    # in the review dialog (the refinement still returns its best box but the
    # user review UI prefers ``unchanged`` under this threshold).
    low_confidence_threshold: float = 0.6
    high_confidence_threshold: float = 0.8

    # CLAHE parameters.
    clahe_clip_limit: float = 2.0
    clahe_tile_grid: tuple[int, int] = (8, 8)

    # Morphological-close kernel size relative to the ROI's min side. Smaller
    # kernels bridge the gaps between plate characters without also bridging
    # the plate body to adjacent dark structures (bike bodywork, shadows).
    morph_kernel_fraction: float = 0.04

    # Minimum working resolution (pixels on the short side) for the analysis
    # pipeline. Small plate crops (e.g. 34x26 px on 1080p footage) are
    # upscaled to at least this many pixels so flood-fill / Canny /
    # thresholding have real transitions to lock onto. Upscaling is applied
    # only for detection — the final refined box is mapped back to
    # original-frame coordinates.
    min_analysis_side: int = 120


@dataclass(frozen=True)
class RefinementResult:
    """Outcome of one :func:`refine_box` call."""

    box: PlateBox
    confidence: float  # refiner-internal score in [0.0, 1.0]
    method: RefineMethod
    # Diagnostic fields used by tests and the review dialog — not persisted.
    details: dict = field(default_factory=dict)


def _unchanged(box: PlateBox, details: dict | None = None) -> RefinementResult:
    return RefinementResult(
        box=box, confidence=0.0, method="unchanged",
        details=details or {},
    )


def _normalize_angle(angle_deg: float) -> float:
    """Map any angle into ``(-45, 45]`` by adding/subtracting 90° multiples.

    A rectangle at +80° is the same physical shape as one at -10° with its w/h
    swapped — for scoring the angle we care about the acute deviation from
    axis-aligned, not the raw minAreaRect output.
    """
    a = ((angle_deg + 45.0) % 90.0) - 45.0
    return a


def _contour_to_norm_box(
    contour: np.ndarray,
    roi_x: int,
    roi_y: int,
    frame_w: int,
    frame_h: int,
    scale: float = 1.0,
) -> tuple[PlateBox, float]:
    """Convert a contour (in **scaled** ROI pixel coords) into an oriented
    normalized box. ``scale`` is the upscale factor applied to the ROI before
    analysis; contour coords are divided by it to return to the original ROI
    pixel space.
    """
    (cx_roi, cy_roi), (w_roi, h_roi), angle = cv2.minAreaRect(contour)
    if w_roi < h_roi:
        w_roi, h_roi = h_roi, w_roi
        angle += 90.0
    norm_angle = _normalize_angle(angle)
    cx_frame = cx_roi / scale + roi_x
    cy_frame = cy_roi / scale + roi_y
    w_frame = w_roi / scale
    h_frame = h_roi / scale
    nx = (cx_frame - w_frame / 2.0) / frame_w
    ny = (cy_frame - h_frame / 2.0) / frame_h
    nw = w_frame / frame_w
    nh = h_frame / frame_h
    return (
        PlateBox(x=nx, y=ny, w=nw, h=nh, angle=norm_angle),
        norm_angle,
    )


def _containment_score(candidate: PlateBox, input_box: PlateBox) -> float:
    """Fraction of the candidate's AABB envelope that lies inside the input
    box's AABB envelope. Peaks at 1.0 when the candidate is fully contained.
    """
    ax, ay, aw, ah = candidate.aabb_envelope()
    bx, by, bw, bh = input_box.aabb_envelope()
    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(ax + aw, bx + bw)
    inter_y2 = min(ay + ah, by + bh)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    cand_area = max(aw * ah, 1e-9)
    return inter / cand_area


def _centre_proximity(candidate: PlateBox, input_box: PlateBox) -> float:
    """How close the candidate's centre is to the input box's centre, in
    [0, 1]. Peaks at 1.0 when centres match and decays to 0 when the offset
    reaches half the input's larger side.

    This term breaks ties where two candidates have similar size and edge
    density but different positions — e.g. a half-plate box offset to one
    side of the plate vs. a full-plate box centred on it.
    """
    ax, ay, aw, ah = candidate.aabb_envelope()
    bx, by, bw, bh = input_box.aabb_envelope()
    cand_cx = ax + aw / 2
    cand_cy = ay + ah / 2
    input_cx = bx + bw / 2
    input_cy = by + bh / 2
    max_dev = max(bw, bh) / 2
    if max_dev <= 0:
        return 1.0
    dist = math.hypot(cand_cx - input_cx, cand_cy - input_cy)
    return max(0.0, 1.0 - dist / max_dev)


def _size_proximity(candidate: PlateBox, input_box: PlateBox) -> float:
    """Plateau-style size score in [0, 1]. Peaks when the candidate area is
    50-85% of the input — the expected range for a correctly-refined plate,
    given the detector's 15% outward padding on each side. Both extremes are
    penalised:

    * Below 50% (e.g. just-the-letters at ~25-30%): linear decay to 0 at 20%.
    * Above 85% (e.g. the ROI-filling blob at ~100%): rapid decay to 0 at
      ratio ≈ 1.05, so input-sized candidates can't win by default.
    """
    ax, ay, aw, ah = candidate.aabb_envelope()
    bx, by, bw, bh = input_box.aabb_envelope()
    cand_area = max(aw * ah, 1e-9)
    input_area = max(bw * bh, 1e-9)
    ratio = cand_area / input_area
    if 0.5 <= ratio <= 0.85:
        return 1.0
    if ratio < 0.5:
        # 0.5 → 1.0, 0.2 → 0.0, below 0.2 → 0.
        return max(0.0, (ratio - 0.2) / 0.3)
    # ratio > 0.85: 0.85 → 1.0, 1.05 → 0.0 (and anything larger stays at 0).
    return max(0.0, 1.0 - (ratio - 0.85) * 5.0)


def _edge_density(edges: np.ndarray, candidate: PlateBox, roi_x: int, roi_y: int,
                  frame_w: int, frame_h: int, scale: float = 1.0) -> float:
    """Mean edge response along the candidate's **perimeter** (not interior).

    Perimeter-based scoring rewards candidates whose outline sits on the
    plate's dark frame — strong edge response there — and penalises
    inner-bounding-box candidates (e.g. the text-only region) whose
    perimeter sits in the plate's uniform interior with no edges.

    ``edges`` is the Canny output at the (possibly upscaled) ROI resolution;
    the candidate is in original-frame normalized coords, so each corner
    must be mapped back through the ROI origin AND multiplied by the
    upscale ``scale`` to land on the right pixel.
    """
    corners = [
        [
            int(round((cx - roi_x) * scale)),
            int(round((cy - roi_y) * scale)),
        ]
        for cx, cy in candidate.corners_px(frame_w, frame_h)
    ]
    poly = np.array(corners, dtype=np.int32)
    mask = np.zeros(edges.shape[:2], dtype=np.uint8)
    # Polyline thickness of 2 px tolerates sub-pixel misalignment between
    # the candidate's idealised rectangle and the real plate border.
    cv2.polylines(mask, [poly], isClosed=True, color=255, thickness=2)
    inside = cv2.countNonZero(mask)
    if inside == 0:
        return 0.0
    total_edge = float(cv2.mean(edges, mask=mask)[0])
    return total_edge / 255.0


def _aspect_penalty(box: PlateBox) -> float:
    """Return 1.0 for an ideal plate-like aspect, decaying to 0.0 for extremes.

    Both long European car plates (~4.6:1) and square-ish motorcycle / JP
    plates (~1.1:1) are treated as valid shapes; the sweet spot is a flat
    plateau from 1.0 to 5.0 so neither shape is penalised. Non-plate-like
    extremes (e.g. stretched text blocks) still score low.
    """
    w = max(box.w, 1e-9)
    h = max(box.h, 1e-9)
    ratio = max(w / h, h / w)
    if 1.0 <= ratio <= 5.0:
        return 1.0
    return max(0.0, 1.0 - (ratio - 5.0) * 0.2)


def _score_candidate(candidate: PlateBox, input_box: PlateBox, edges: np.ndarray,
                     roi_x: int, roi_y: int, frame_w: int, frame_h: int,
                     scale: float = 1.0) -> float:
    """Weighted blend of five [0, 1] terms:

    * ``containment`` — fraction of candidate inside the input box.
    * ``size`` — candidate area relative to input; plateau at 50-85%.
    * ``centre`` — candidate centre near input centre; prevents half-plate
      candidates offset to one side from winning.
    * ``edge`` — edge response along the candidate's perimeter.
    * ``aspect`` — plate-like aspect-ratio bonus.
    """
    containment = _containment_score(candidate, input_box)
    size = _size_proximity(candidate, input_box)
    centre = _centre_proximity(candidate, input_box)
    edge = _edge_density(
        edges, candidate, roi_x, roi_y, frame_w, frame_h, scale=scale,
    )
    aspect = _aspect_penalty(candidate)
    return (
        0.20 * containment
        + 0.30 * size
        + 0.20 * centre
        + 0.20 * edge
        + 0.10 * aspect
    )


def _floodfill_mask(
    gray: np.ndarray,
    seed: tuple[int, int],
    lo: int,
    hi: int,
) -> np.ndarray:
    """Return the connected region a Photoshop-style "magic wand" click at
    *seed* would select under a tolerance of ``[lo, hi]`` grayscale levels.

    Uses ``FLOODFILL_FIXED_RANGE`` so the tolerance is measured against the
    **seed pixel's value**, not the growing frontier. Without this flag,
    floodFill can creep through an anti-aliased plate border (seed 220 →
    frontier 180 → 140 → 100 → …) and end up filling the bodywork on the
    other side — which is what breaks refinement on tight plate crops.
    """
    h, w = gray.shape[:2]
    # floodFill requires a mask 2px larger than the image on each axis.
    mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    # FLOODFILL_MASK_ONLY: leave the image alone, fill only the mask.
    # (255 << 8): value written into the mask for filled pixels.
    # 4: 4-connected neighbourhood.
    # FIXED_RANGE: tolerance is seed-relative, not frontier-relative.
    flags = (
        cv2.FLOODFILL_MASK_ONLY
        | cv2.FLOODFILL_FIXED_RANGE
        | (255 << 8)
        | 4
    )
    cv2.floodFill(
        gray.copy(), mask, seed, 0,
        loDiff=lo, upDiff=hi, flags=flags,
    )
    # Strip the 1-px border floodFill adds.
    return mask[1:-1, 1:-1]


def _preprocess_roi(roi_bgr: np.ndarray, cfg: RefinerConfig) -> list[np.ndarray]:
    """Return a list of binary masks highlighting plate-like structures.

    Multiple detection strategies run in parallel so the scoring stage can
    pick the best candidate:

    1. **Magic-wand flood fills** (primary). Several seed points inside the
       ROI select connected regions of similar luminance. This mirrors the
       manual GIMP/Photoshop workflow and succeeds because the fill respects
       plate-border connectivity — it does not leap across the plate's dark
       frame into adjacent bodywork.
    2. Canny edges (dilated) — catches rectangular borders without depending
       on brightness polarity.
    3. Adaptive ``THRESH_BINARY`` / ``THRESH_BINARY_INV`` — fallbacks for
       flat-border plates where there's no strong luminance step.
    """
    if roi_bgr.ndim == 3:
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = roi_bgr
    clahe = cv2.createCLAHE(
        clipLimit=cfg.clahe_clip_limit, tileGridSize=cfg.clahe_tile_grid,
    )
    gray = clahe.apply(gray)

    h, w = gray.shape[:2]
    block = max(11, (min(h, w) // 10) | 1)  # odd
    min_side = min(h, w)
    k = max(3, int(min_side * cfg.morph_kernel_fraction) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))

    masks: list[np.ndarray] = []

    # Strategy 1 — flood-fill magic-wand seeds. We seed at points likely to
    # land on the plate's bright interior: the ROI centre plus four
    # quadrant-inside points. Each seed is only used if its pixel is in the
    # upper half of the ROI's luminance histogram — a dark text pixel would
    # flood the wrong connected region.
    roi_median = float(np.median(gray))
    bright_threshold = roi_median  # only seed on pixels brighter than the median
    seeds = [
        (w // 2, h // 2),
        (w // 3, h // 3),
        (2 * w // 3, h // 3),
        (w // 3, 2 * h // 3),
        (2 * w // 3, 2 * h // 3),
    ]
    for (sx, sy) in seeds:
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        if gray[sy, sx] < bright_threshold:
            continue  # landed on plate text — the fill would capture the wrong region
        ff = _floodfill_mask(gray, (sx, sy), lo=30, hi=30)
        if cv2.countNonZero(ff) > 0:
            masks.append(cv2.morphologyEx(ff, cv2.MORPH_CLOSE, kernel))

    # Strategy 2 — Canny edges dilated, for rectangular-border detection.
    edges = cv2.Canny(gray, 50, 150)
    masks.append(cv2.dilate(edges, kernel, iterations=1))

    # Strategies 3 & 4 — adaptive thresholds, both polarities (fallback).
    for mode in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, mode, block, 5,
        )
        masks.append(cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel))
    return masks


def refine_box(
    frame: np.ndarray,
    box: PlateBox,
    cfg: RefinerConfig | None = None,
) -> RefinementResult:
    """Refine one :class:`PlateBox` using image analysis over its ROI.

    Parameters
    ----------
    frame : np.ndarray
        BGR video frame (H, W, 3) or grayscale (H, W).
    box : PlateBox
        The existing box to refine. Its ``angle`` is ignored on input — the
        refiner always starts from the box's AABB envelope.
    cfg : RefinerConfig, optional
        Thresholds. Defaults are tuned for 1080p trail-cam footage.
    """
    if cfg is None:
        cfg = RefinerConfig()
    if frame.size == 0 or box.w <= 0 or box.h <= 0:
        return _unchanged(box)

    frame_h, frame_w = frame.shape[:2]

    # Start from the AABB envelope so we can operate on an axis-aligned ROI.
    env_x, env_y, env_w, env_h = box.aabb_envelope()
    pad_w = env_w * cfg.roi_padding
    pad_h = env_h * cfg.roi_padding
    roi_x1 = max(0, int(round((env_x - pad_w) * frame_w)))
    roi_y1 = max(0, int(round((env_y - pad_h) * frame_h)))
    roi_x2 = min(frame_w, int(round((env_x + env_w + pad_w) * frame_w)))
    roi_y2 = min(frame_h, int(round((env_y + env_h + pad_h) * frame_h)))
    if roi_x2 - roi_x1 < 8 or roi_y2 - roi_y1 < 8:
        return _unchanged(box)

    roi = frame[roi_y1:roi_y2, roi_x1:roi_x2]

    # Upscale the ROI when it's small so the detection pipeline has enough
    # pixel resolution to discriminate plate border from adjacent structures.
    roi_min_side = min(roi.shape[:2])
    scale = 1.0
    if roi_min_side < cfg.min_analysis_side:
        scale = cfg.min_analysis_side / roi_min_side
        roi = cv2.resize(
            roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC,
        )

    masks = _preprocess_roi(roi, cfg)
    edges = cv2.Canny(
        cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi,
        50, 150,
    )

    contours: list = []
    for mask in masks:
        found, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )
        contours.extend(found)
    if not contours:
        return _unchanged(box, {"reason": "no_contours", "scale": round(scale, 2)})

    input_area_norm = max(box.w * box.h, 1e-9)
    input_cx = box.x + box.w / 2.0
    input_cy = box.y + box.h / 2.0
    max_side_norm = max(box.w, box.h)

    best_aabb: tuple[PlateBox, float] | None = None
    best_oriented: tuple[PlateBox, float, float] | None = None  # (box, score, angle)

    diag = {
        "contours_total": len(contours),
        "rejected_short": 0,
        "rejected_degenerate": 0,
        "rejected_area": 0,
        "rejected_aspect": 0,
        "rejected_centre": 0,
        "accepted": 0,
        "best_aspect_seen": None,
        "best_area_ratio_seen": None,
        "roi_px": (roi_x2 - roi_x1, roi_y2 - roi_y1),
        "input_box_px": (
            int(round(box.w * frame_w)), int(round(box.h * frame_h)),
        ),
        "analysis_scale": round(scale, 2),
        "candidates": [],
    }

    for contour in contours:
        if len(contour) < 5:
            diag["rejected_short"] += 1
            continue

        # Two candidates per contour: the rotated minAreaRect (oriented) and
        # the axis-aligned boundingRect (AABB). They describe the same blob
        # but with different geometries, so whichever better fits the plate
        # will have denser edges within its own footprint.
        candidate_oriented, raw_angle = _contour_to_norm_box(
            contour, roi_x1, roi_y1, frame_w, frame_h, scale=scale,
        )
        if candidate_oriented.w <= 0 or candidate_oriented.h <= 0:
            diag["rejected_degenerate"] += 1
            continue

        bx_px, by_px, bw_px, bh_px = cv2.boundingRect(contour)
        # boundingRect is in scaled ROI coords; divide by scale to get back
        # to original ROI coords before adding roi_x/roi_y and normalizing.
        candidate_aabb = PlateBox(
            x=(bx_px / scale + roi_x1) / frame_w,
            y=(by_px / scale + roi_y1) / frame_h,
            w=(bw_px / scale) / frame_w,
            h=(bh_px / scale) / frame_h,
            angle=0.0,
        )
        if candidate_aabb.w <= 0 or candidate_aabb.h <= 0:
            diag["rejected_degenerate"] += 1
            continue

        # Filter using the *smaller* of the two candidates — if either of
        # them passes, the contour is a plausible plate candidate and scoring
        # decides between oriented and AABB.
        env = candidate_oriented.aabb_envelope()
        area_oriented = max(env[2] * env[3], 1e-9)
        area_aabb = max(candidate_aabb.w * candidate_aabb.h, 1e-9)
        area_ratio = min(area_oriented, area_aabb) / input_area_norm
        if diag["best_area_ratio_seen"] is None or abs(area_ratio - 1.0) < abs(
            diag["best_area_ratio_seen"] - 1.0,
        ):
            diag["best_area_ratio_seen"] = float(area_ratio)
        if area_ratio < cfg.min_area_fraction or area_ratio > cfg.max_area_fraction:
            diag["rejected_area"] += 1
            continue

        # Aspect filter on the oriented rectangle (its own w/h).
        long_side = max(candidate_oriented.w, candidate_oriented.h)
        short_side = max(min(candidate_oriented.w, candidate_oriented.h), 1e-9)
        aspect = long_side / short_side
        if diag["best_aspect_seen"] is None or (
            cfg.min_aspect_ratio <= aspect <= cfg.max_aspect_ratio
        ) or abs(aspect - 2.0) < abs(diag["best_aspect_seen"] - 2.0):
            diag["best_aspect_seen"] = float(aspect)
        if aspect < cfg.min_aspect_ratio or aspect > cfg.max_aspect_ratio:
            diag["rejected_aspect"] += 1
            continue

        # Centre distance filter (oriented and AABB share a centre up to
        # rounding, use the oriented one as the reference).
        cand_cx = candidate_oriented.x + candidate_oriented.w / 2.0
        cand_cy = candidate_oriented.y + candidate_oriented.h / 2.0
        dist = math.hypot(cand_cx - input_cx, cand_cy - input_cy)
        if dist > cfg.max_centre_distance * max_side_norm:
            diag["rejected_centre"] += 1
            continue

        diag["accepted"] += 1

        oriented_score = _score_candidate(
            candidate_oriented, box, edges, roi_x1, roi_y1, frame_w, frame_h,
            scale=scale,
        )
        aabb_score = _score_candidate(
            candidate_aabb, box, edges, roi_x1, roi_y1, frame_w, frame_h,
            scale=scale,
        )

        # Per-candidate px dimensions + scores for debugging.
        diag["candidates"].append({
            "aabb_wh_px": (
                int(round(candidate_aabb.w * frame_w)),
                int(round(candidate_aabb.h * frame_h)),
            ),
            "aabb_score": round(aabb_score, 3),
            "oriented_wh_px": (
                int(round(candidate_oriented.w * frame_w)),
                int(round(candidate_oriented.h * frame_h)),
            ),
            "oriented_angle": round(raw_angle, 2),
            "oriented_score": round(oriented_score, 3),
        })

        if best_aabb is None or aabb_score > best_aabb[1]:
            best_aabb = (candidate_aabb, aabb_score)
        if abs(raw_angle) >= cfg.min_oriented_angle_deg:
            if best_oriented is None or oriented_score > best_oriented[1]:
                best_oriented = (candidate_oriented, oriented_score, raw_angle)

    logger.debug(
        "refine_box: contours=%d accepted=%d rejected_area=%d rejected_aspect=%d "
        "rejected_centre=%d best_aspect=%s best_area_ratio=%s",
        diag["contours_total"], diag["accepted"], diag["rejected_area"],
        diag["rejected_aspect"], diag["rejected_centre"],
        diag["best_aspect_seen"], diag["best_area_ratio_seen"],
    )

    # Propagate diagnostics into every code path so the Debug log shows the
    # full picture — not only the unchanged path.
    shared_diag = dict(diag)

    if best_aabb is None:
        return _unchanged(box, shared_diag)

    # Preserve detection metadata; refiner confidence rides in RefinementResult.
    def _with_meta(b: PlateBox) -> PlateBox:
        return PlateBox(
            x=max(0.0, min(1.0, b.x)),
            y=max(0.0, min(1.0, b.y)),
            w=max(1e-6, min(1.0, b.w)),
            h=max(1e-6, min(1.0, b.h)),
            confidence=box.confidence,
            manual=box.manual,
            angle=b.angle,
        )

    best_aabb_box, best_aabb_score = best_aabb
    if (
        best_oriented is not None
        and best_oriented[1] > best_aabb_score
    ):
        shared_diag.update({
            "aabb_score": best_aabb_score,
            "aabb_box": (
                best_aabb_box.x, best_aabb_box.y,
                best_aabb_box.w, best_aabb_box.h,
            ),
            "oriented_score": best_oriented[1],
            "oriented_box": (
                best_oriented[0].x, best_oriented[0].y,
                best_oriented[0].w, best_oriented[0].h,
                best_oriented[2],
            ),
            "raw_angle": best_oriented[2],
        })
        return RefinementResult(
            box=_with_meta(best_oriented[0]),
            confidence=float(best_oriented[1]),
            method="oriented",
            details=shared_diag,
        )
    shared_diag.update({
        "aabb_score": best_aabb_score,
        "aabb_box": (
            best_aabb_box.x, best_aabb_box.y,
            best_aabb_box.w, best_aabb_box.h,
        ),
        "oriented_best": (
            None if best_oriented is None else {
                "score": best_oriented[1],
                "angle": best_oriented[2],
                "wh": (best_oriented[0].w, best_oriented[0].h),
            }
        ),
    })
    return RefinementResult(
        box=_with_meta(best_aabb_box),
        confidence=float(best_aabb_score),
        method="aabb",
        details=shared_diag,
    )
