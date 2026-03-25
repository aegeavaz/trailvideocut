#!/usr/bin/env python3
"""Diagnostic script for plate detection pipeline.

Extracts specific frames from a video, runs each detection stage individually,
and saves intermediate images + per-contour pass/fail reports to pinpoint
which filter rejects a plate.

Usage:
    python scripts/diagnose_plate_frames.py VIDEO_PATH --frames 424-428 -o ./plate_diag/
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_frame_range(s: str) -> list[int]:
    """Parse '424-428' or '424,425,426' into a list of frame indices."""
    if "-" in s and "," not in s:
        start, end = s.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(x.strip()) for x in s.split(",")]


def extract_frames(video_path: str, frame_indices: list[int]) -> dict[int, np.ndarray]:
    """Extract specific frames from a video file."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    frames: dict[int, np.ndarray] = {}
    for idx in sorted(frame_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            frames[idx] = frame
        else:
            print(f"  WARNING: Could not read frame {idx}")
    cap.release()
    return frames


def diagnose_frame(
    frame: np.ndarray,
    frame_idx: int,
    output_dir: Path,
) -> dict:
    """Run each pipeline stage and save intermediate results."""
    fdir = output_dir / f"frame_{frame_idx:06d}"
    fdir.mkdir(parents=True, exist_ok=True)

    fh, fw = frame.shape[:2]
    report_lines: list[str] = []
    report_lines.append(f"Frame {frame_idx}  ({fw}x{fh})")
    report_lines.append("=" * 50)

    # --- Stage 1: Preprocessing ---
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blur, 170, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    white_px = int(np.sum(thresh > 0))
    white_pct = white_px / (fw * fh) * 100
    report_lines.append(f"\nSTAGE 1 - Preprocessing")
    report_lines.append(f"  White pixels after threshold(170): {white_px} ({white_pct:.2f}%)")

    cv2.imwrite(str(fdir / "01_grayscale.png"), gray)
    cv2.imwrite(str(fdir / "02_blurred.png"), blur)
    cv2.imwrite(str(fdir / "03_threshold_170.png"), thresh)
    cv2.imwrite(str(fdir / "04_closed.png"), closed)

    # Also save threshold at 165 and 175 for comparison
    for tv in (160, 165, 175, 180):
        _, t = cv2.threshold(blur, tv, 255, cv2.THRESH_BINARY)
        cv2.imwrite(str(fdir / f"03_threshold_{tv}.png"), t)

    # --- Stage 2: Contour extraction + shape filtering ---
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = fw * fh

    report_lines.append(f"\nSTAGE 2 - Contour filtering ({len(contours)} total contours)")

    vis_contours = frame.copy()
    candidates = []
    plate_region_contours = []  # contours near known plate location

    for i, cnt in enumerate(contours):
        rect = cv2.minAreaRect(cnt)
        (cx, cy), (rw, rh), angle = rect
        if rw < rh:
            rw, rh = rh, rw
        if rh == 0:
            continue
        aspect = rw / rh
        area = rw * rh

        # Check if near known plate region (x~1170-1210, y~220-270)
        near_plate = 1150 <= cx <= 1230 and 210 <= cy <= 280

        # Evaluate each filter
        aspect_ok = 1.2 <= aspect <= 1.6
        area_min_ok = area >= 300
        area_max_ok = area <= frame_area * 0.05

        x1 = max(0, int(cx - rw / 2))
        y1 = max(0, int(cy - rh / 2))
        x2 = min(fw, int(cx + rw / 2))
        y2 = min(fh, int(cy + rh / 2))
        bbox_ok = x2 > x1 and y2 > y1

        brightness = 0.0
        contrast = 0.0
        bright_ok = False
        contrast_ok = False
        if bbox_ok:
            roi = gray[y1:y2, x1:x2]
            if roi.size > 0:
                brightness = float(np.mean(roi))
                contrast = float(np.std(roi))
                bright_ok = brightness >= 180
                contrast_ok = contrast >= 15

        all_ok = aspect_ok and area_min_ok and area_max_ok and bbox_ok and bright_ok and contrast_ok

        if near_plate or all_ok:
            reasons = []
            if not aspect_ok:
                reasons.append(f"aspect={aspect:.2f} not in [1.2,1.6]")
            if not area_min_ok:
                reasons.append(f"area={area:.0f} < 300")
            if not area_max_ok:
                reasons.append(f"area={area:.0f} > {frame_area*0.05:.0f}")
            if not bbox_ok:
                reasons.append("bbox invalid")
            if not bright_ok:
                reasons.append(f"brightness={brightness:.1f} < 180")
            if not contrast_ok:
                reasons.append(f"contrast={contrast:.1f} < 15")

            tag = "NEAR_PLATE" if near_plate else ""
            status = "PASS" if all_ok else f"FAIL: {'; '.join(reasons)}"
            report_lines.append(
                f"  Contour {i}: center=({cx:.0f},{cy:.0f}) "
                f"size={rw:.0f}x{rh:.0f} aspect={aspect:.2f} area={area:.0f} "
                f"bright={brightness:.1f} std={contrast:.1f} "
                f"→ {status} {tag}"
            )

            if near_plate:
                plate_region_contours.append({
                    "idx": i, "cx": cx, "cy": cy, "rw": rw, "rh": rh,
                    "aspect": aspect, "area": area, "brightness": brightness,
                    "contrast": contrast, "bbox": (x1, y1, x2, y2),
                    "all_ok": all_ok, "reasons": reasons,
                })

        if all_ok:
            candidates.append((x1, y1, x2, y2))
            color = (0, 255, 0)  # green = pass
        elif near_plate:
            color = (0, 0, 255)  # red = near plate but failed
        else:
            continue  # don't draw irrelevant contours

        cv2.rectangle(vis_contours, (x1, y1), (x2, y2), color, 2)
        label = f"{rw:.0f}x{rh:.0f} a={aspect:.2f}"
        cv2.putText(vis_contours, label, (x1, y1 - 4),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

    cv2.imwrite(str(fdir / "05_contours_annotated.png"), vis_contours)
    report_lines.append(f"  → {len(candidates)} candidates passed shape filters")

    if not plate_region_contours:
        report_lines.append(f"\n  *** NO CONTOURS found near plate region (x~1170-1210, y~220-270) ***")
        report_lines.append(f"  This means the global threshold at 170 failed to produce a white region.")

        # Check brightness in the expected plate region
        px1, py1, px2, py2 = 1170, 220, 1210, 270
        px1 = max(0, min(px1, fw - 1))
        py1 = max(0, min(py1, fh - 1))
        px2 = max(0, min(px2, fw))
        py2 = max(0, min(py2, fh))
        if px2 > px1 and py2 > py1:
            plate_roi = blur[py1:py2, px1:px2]
            report_lines.append(f"\n  Plate region ({px1},{py1})-({px2},{py2}) brightness stats:")
            report_lines.append(f"    Mean: {np.mean(plate_roi):.1f}")
            report_lines.append(f"    Max:  {np.max(plate_roi)}")
            report_lines.append(f"    Min:  {np.min(plate_roi)}")
            report_lines.append(f"    Pixels >= 170: {np.sum(plate_roi >= 170)}/{plate_roi.size}")
            report_lines.append(f"    Pixels >= 165: {np.sum(plate_roi >= 165)}/{plate_roi.size}")
            report_lines.append(f"    Pixels >= 160: {np.sum(plate_roi >= 160)}/{plate_roi.size}")

            # Save zoomed plate region
            plate_region_img = gray[py1:py2, px1:px2]
            scale = 10
            zoomed = cv2.resize(plate_region_img, None, fx=scale, fy=scale,
                                interpolation=cv2.INTER_NEAREST)
            cv2.imwrite(str(fdir / "06_plate_region_zoomed.png"), zoomed)

            # Save threshold results in plate region
            for tv in (160, 165, 170, 175):
                _, t = cv2.threshold(blur[py1:py2, px1:px2], tv, 255, cv2.THRESH_BINARY)
                zoomed_t = cv2.resize(t, None, fx=scale, fy=scale,
                                       interpolation=cv2.INTER_NEAREST)
                cv2.imwrite(str(fdir / f"06_plate_region_thresh_{tv}.png"), zoomed_t)

    # --- Stage 3: Exclusion zone check ---
    report_lines.append(f"\nSTAGE 3 - Exclusion zone")
    after_excl = []
    for bbox in candidates:
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        in_mid_x = fw / 3 <= cx <= 2 * fw / 3
        in_bot_y = cy >= fh * 0.80
        excluded = in_mid_x and in_bot_y
        report_lines.append(
            f"  ({x1},{y1},{x2},{y2}) center=({cx:.0f},{cy:.0f}) "
            f"mid_x={in_mid_x} bot_y={in_bot_y} → {'EXCLUDED' if excluded else 'PASS'}"
        )
        if not excluded:
            after_excl.append(bbox)
    report_lines.append(f"  → {len(after_excl)} candidates after exclusion")

    # --- Stage 4: Character grid validation ---
    report_lines.append(f"\nSTAGE 4 - Character grid validation")
    final_plates = []
    for bbox in after_excl:
        x1, y1, x2, y2 = bbox
        roi = gray[y1:y2, x1:x2]
        roi_h, roi_w = roi.shape[:2]
        report_lines.append(f"\n  Candidate ({x1},{y1},{x2},{y2}) ROI={roi_w}x{roi_h}")

        if roi_h < 8 or roi_w < 15:
            report_lines.append(f"    FAIL: ROI too small (min 15x8)")
            continue

        block = min(15, roi_w | 1, roi_h | 1)
        report_lines.append(f"    blockSize={block} (roi covers {block/roi_h*100:.0f}% height, {block/roi_w*100:.0f}% width)")

        binary = cv2.adaptiveThreshold(
            roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, blockSize=block, C=10,
        )

        # Save binary (upscaled)
        scale = 10
        zoomed_bin = cv2.resize(binary, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(str(fdir / f"07_char_binary_{x1}_{y1}.png"), zoomed_bin)

        contours_c, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        report_lines.append(f"    Raw contours: {len(contours_c)}")

        char_bboxes = []
        for j, cnt_c in enumerate(contours_c):
            x, y, w, h = cv2.boundingRect(cnt_c)
            area_c = w * h
            h_ratio = h / roi_h
            w_ratio = w / roi_w

            area_ok = area_c >= 15
            h_ok = 0.20 <= h_ratio <= 0.85
            w_ok = 0.02 <= w_ratio <= 0.25
            all_char_ok = area_ok and h_ok and w_ok

            reasons = []
            if not area_ok:
                reasons.append(f"area={area_c}<15")
            if not h_ok:
                reasons.append(f"h_ratio={h_ratio:.2f} not in [0.20,0.85]")
            if not w_ok:
                reasons.append(f"w_ratio={w_ratio:.2f} not in [0.02,0.25]")

            status = "PASS" if all_char_ok else f"FAIL: {'; '.join(reasons)}"
            report_lines.append(
                f"    Char {j}: pos=({x},{y}) size={w}x{h} area={area_c} "
                f"h_r={h_ratio:.2f} w_r={w_ratio:.2f} → {status}"
            )
            if all_char_ok:
                char_bboxes.append((x, y, w, h))

        report_lines.append(f"    Passing characters: {len(char_bboxes)} (need 3-10)")

        if len(char_bboxes) < 3:
            report_lines.append(f"    FAIL: Too few characters ({len(char_bboxes)} < 3)")
            continue
        if len(char_bboxes) > 10:
            report_lines.append(f"    FAIL: Too many characters ({len(char_bboxes)} > 10)")
            continue

        heights = np.array([h for _, _, _, h in char_bboxes], dtype=float)
        mean_h = float(np.mean(heights))
        h_std = float(np.std(heights))
        h_consist = h_std / mean_h if mean_h > 0 else 999
        report_lines.append(f"    Height consistency: std/mean = {h_std:.2f}/{mean_h:.2f} = {h_consist:.3f} (max 0.5)")

        if h_consist > 0.5:
            report_lines.append(f"    FAIL: Height inconsistency ({h_consist:.3f} > 0.5)")
            continue

        centers_y = np.array([y + h / 2 for _, y, _, h in char_bboxes], dtype=float)
        align = float(np.std(centers_y)) / roi_h
        report_lines.append(f"    Vertical alignment: std/roi_h = {np.std(centers_y):.2f}/{roi_h} = {align:.3f} (max 0.35)")

        if align > 0.35:
            report_lines.append(f"    FAIL: Poor alignment ({align:.3f} > 0.35)")
            continue

        report_lines.append(f"    PASS: Character validation succeeded")
        final_plates.append(bbox)

    # --- Stage 5: Summary ---
    report_lines.append(f"\nFINAL RESULT: {len(final_plates)} plates detected")
    for p in final_plates:
        report_lines.append(f"  {p}")

    report_text = "\n".join(report_lines)
    (fdir / "report.txt").write_text(report_text + "\n")
    print(report_text)
    print()

    return {
        "frame_idx": frame_idx,
        "candidates_shape": len(candidates),
        "candidates_excl": len(after_excl),
        "final_plates": len(final_plates),
        "plate_region_contours": plate_region_contours,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose plate detection on specific frames")
    parser.add_argument("video", type=str, help="Input video file")
    parser.add_argument("--frames", type=str, default="424-428",
                        help="Frame range (e.g., '424-428' or '424,425,426')")
    parser.add_argument("-o", "--output", type=Path, default=Path("./plate_diag"),
                        help="Output directory")
    args = parser.parse_args()

    frame_indices = parse_frame_range(args.frames)
    print(f"Extracting frames {frame_indices} from {args.video}")
    frames = extract_frames(args.video, frame_indices)

    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for idx in sorted(frames.keys()):
        results.append(diagnose_frame(frames[idx], idx, args.output))

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Frame':<10} {'Shape':>8} {'Excl':>8} {'Final':>8} {'Plate region':>30}")
    print("-" * 70)
    for r in results:
        plate_info = ""
        if r["plate_region_contours"]:
            c = r["plate_region_contours"][0]
            plate_info = f"asp={c['aspect']:.2f} brt={c['brightness']:.0f} ok={c['all_ok']}"
        else:
            plate_info = "NO CONTOUR"
        print(f"{r['frame_idx']:<10} {r['candidates_shape']:>8} {r['candidates_excl']:>8} "
              f"{r['final_plates']:>8} {plate_info:>30}")

    summary_path = args.output / "summary.txt"
    print(f"\nDetailed reports saved to {args.output}/")


if __name__ == "__main__":
    main()
