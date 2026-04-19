"""Integration test: MP4 plate-blur export aligns with source-frame keys.

Pins the invariant codified in the `plate-blur-export` spec's
`FFmpeg PlateBlurProcessor uses exact source-frame key lookup`
requirement: for every decoded source frame N,
`PlateBlurProcessor.process_segment` must look up blur boxes via
`detections[N]`, not `detections[N+1]` or `detections[N-1]`.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from trailvideocut.plate.blur import PlateBlurProcessor
from trailvideocut.plate.models import ClipPlateData, PlateBox


FPS = 30.0
NUM_FRAMES = 60
WIDTH = 320
HEIGHT = 240


def _make_frame_number_clip(path: Path) -> None:
    """Write a deterministic MP4 where each frame shares the same checkerboard
    body but a unique top-strip colour band encoding the frame index.

    The checkerboard body has high spatial frequency, so applying Gaussian blur
    visibly reduces its pixel-value standard deviation — a simple signal the
    test uses to detect "this region was blurred".
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        pytest.skip("cv2.VideoWriter could not open mp4v encoder in this environment")

    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    checker = (((xx // 4) + (yy // 4)) % 2).astype(np.uint8) * 255
    body = np.stack([checker, checker, checker], axis=-1)

    try:
        for n in range(NUM_FRAMES):
            frame = body.copy()
            frame[:10] = (n & 0xFF, (n >> 4) & 0xFF, (n * 7) & 0xFF)
            writer.write(frame)
    finally:
        writer.release()


LEFT_BOX = PlateBox(x=0.05, y=0.35, w=0.22, h=0.30)
CENTER_BOX = PlateBox(x=0.39, y=0.35, w=0.22, h=0.30)
RIGHT_BOX = PlateBox(x=0.73, y=0.35, w=0.22, h=0.30)
REGIONS = (LEFT_BOX, CENTER_BOX, RIGHT_BOX)


def _box_pixel_slice(box: PlateBox) -> tuple[slice, slice]:
    x0 = int(box.x * WIDTH)
    y0 = int(box.y * HEIGHT)
    x1 = int((box.x + box.w) * WIDTH)
    y1 = int((box.y + box.h) * HEIGHT)
    return (slice(y0, y1), slice(x0, x1))


def _read_yuv_i420_frames(path: Path) -> list[np.ndarray]:
    """Decode the I420 raw stream written by ``process_segment``."""
    frame_bytes = WIDTH * HEIGHT * 3 // 2
    data = path.read_bytes()
    count = len(data) // frame_bytes
    frames = []
    for i in range(count):
        chunk = data[i * frame_bytes : (i + 1) * frame_bytes]
        yuv = np.frombuffer(chunk, dtype=np.uint8).reshape(HEIGHT * 3 // 2, WIDTH)
        bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
        frames.append(bgr)
    return frames


def test_process_segment_uses_exact_source_frame_key(tmp_path):
    clip_path = tmp_path / "frame_number.mp4"
    _make_frame_number_clip(clip_path)

    detections: dict[int, list[PlateBox]] = {}
    for n in range(1, NUM_FRAMES - 1):
        detections[n] = [REGIONS[n % 3]]

    cpd = ClipPlateData(clip_index=0, detections=detections)

    processor = PlateBlurProcessor(
        video_path=clip_path,
        segment_start=0.0,
        segment_duration=NUM_FRAMES / FPS,
        clip_plate_data=cpd,
        fps=FPS,
        frame_width=WIDTH,
        frame_height=HEIGHT,
        clip_index=0,
    )

    try:
        tmp_yuv, frames_written = processor.process_segment()
        assert frames_written >= NUM_FRAMES - 2, (
            f"expected near-full segment output, got {frames_written}"
        )
        decoded = _read_yuv_i420_frames(tmp_yuv)
    finally:
        if "tmp_yuv" in locals():
            tmp_yuv.unlink(missing_ok=True)

    assert len(decoded) == frames_written, (
        f"decoded {len(decoded)} frames, expected {frames_written}"
    )

    unblurred_reference = max(
        float(np.std(decoded[0][_box_pixel_slice(region)])) for region in REGIONS
    )
    blur_threshold = unblurred_reference * 0.6

    probed = 0
    for n in (10, 15, 20, 30, 40, 50):
        if n >= len(decoded):
            continue
        probed += 1
        expected_blur_region = REGIONS[n % 3]
        other_regions = [r for r in REGIONS if r is not expected_blur_region]

        frame = decoded[n]
        expected_slice = _box_pixel_slice(expected_blur_region)
        expected_std = float(np.std(frame[expected_slice]))

        other_stds = [float(np.std(frame[_box_pixel_slice(r)])) for r in other_regions]

        assert expected_std < blur_threshold, (
            f"frame {n}: expected blur in region {REGIONS.index(expected_blur_region)} "
            f"(n%3={n % 3}), but std={expected_std:.1f} >= threshold={blur_threshold:.1f}. "
            f"This indicates the lookup landed on detections[{n - 1}] or detections[{n + 1}] "
            f"instead of detections[{n}]."
        )
        for r, s in zip(other_regions, other_stds):
            assert s >= blur_threshold, (
                f"frame {n}: region {REGIONS.index(r)} "
                f"was blurred unexpectedly (std={s:.1f} < threshold={blur_threshold:.1f}). "
                f"Only detections[{n}] was set for frame {n}; an offset is active."
            )

    assert probed >= 4, "too few frames probed — fixture may have failed"
