"""Tests for the license plate blurring feature."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np


class TestBlurRegion:
    """Tests for PlateBlurrer.blur_region."""

    def test_blur_region_applies_gaussian(self):
        from trailvideocut.editor.plate_blur import PlateBlurrer

        blurrer = PlateBlurrer()
        frame = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)
        bbox = (20, 10, 80, 50)

        original_roi = frame[10:50, 20:80].copy()
        original_var = np.var(original_roi)

        blurrer.blur_region(frame, bbox)

        blurred_roi = frame[10:50, 20:80]
        blurred_var = np.var(blurred_roi)

        assert blurred_var < original_var

    def test_blur_region_preserves_outside(self):
        from trailvideocut.editor.plate_blur import PlateBlurrer

        blurrer = PlateBlurrer()
        frame = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)
        bbox = (20, 10, 80, 50)

        outside_before = frame[60:90, 100:180].copy()
        blurrer.blur_region(frame, bbox)
        outside_after = frame[60:90, 100:180]

        np.testing.assert_array_equal(outside_before, outside_after)

    def test_blur_region_empty_roi(self):
        from trailvideocut.editor.plate_blur import PlateBlurrer

        blurrer = PlateBlurrer()
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        result = blurrer.blur_region(frame, (50, 50, 50, 50))
        assert result is frame


class TestPlateShapeDetector:
    """Tests for PlateShapeDetector."""

    def test_detects_white_rectangle_with_text(self):
        """A bright white rectangle with dark text (plate-like) is detected."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        # Dark frame with a white rectangle matching current aspect filter
        frame = np.full((400, 800, 3), 60, dtype=np.uint8)
        # 30x22 white rect → aspect ~1.4 (within 1.2-1.5 filter)
        frame[180:202, 380:410] = 240
        # Dark text marks for contrast
        frame[185:197, 388:394] = 30
        frame[185:197, 398:404] = 30

        plates = detector.detect(frame)
        assert len(plates) >= 1

    def test_ignores_dark_rectangle(self):
        """A dark rectangle (low brightness) is not detected."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        frame = np.full((200, 400, 3), 120, dtype=np.uint8)
        frame[80:100, 150:230] = 40

        plates = detector.detect(frame)
        assert len(plates) == 0

    def test_ignores_oversized(self):
        """A huge white rectangle (>5% of frame) is not detected."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        frame = np.full((200, 400, 3), 60, dtype=np.uint8)
        frame[20:180, 20:380] = 240  # covers most of the frame

        plates = detector.detect(frame)
        assert len(plates) == 0

    def test_empty_frame(self):
        """Uniform frame produces no detections."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        frame = np.full((200, 400, 3), 128, dtype=np.uint8)

        plates = detector.detect(frame)
        assert len(plates) == 0


class TestBlurPlatesPipeline:
    """Integration test for the full blur_plates pipeline with mocked detection."""

    def test_blur_plates_processes_all_frames(self):
        from trailvideocut.editor.plate_blur import PlateBlurrer

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        fourcc = cv2.VideoWriter.fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp_path, fourcc, 30.0, (200, 100))
        for _ in range(5):
            frame = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)
            writer.write(frame)
        writer.release()

        output_path = tmp_path.replace(".mp4", "_blurred.mp4")

        blurrer = PlateBlurrer()
        mock_detector = MagicMock()
        mock_detector.detect.return_value = [(30, 20, 150, 60)]
        blurrer._detector = mock_detector

        progress_calls = []

        try:
            blurrer.blur_plates(
                tmp_path,
                output_path,
                progress_callback=lambda cur, tot: progress_calls.append((cur, tot)),
            )

            assert Path(output_path).exists()
            assert len(progress_calls) == 5
            assert mock_detector.detect.call_count == 5
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)

    def test_blur_plates_in_place(self):
        from trailvideocut.editor.plate_blur import PlateBlurrer

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        fourcc = cv2.VideoWriter.fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp_path, fourcc, 30.0, (200, 100))
        for _ in range(3):
            frame = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)
            writer.write(frame)
        writer.release()

        blurrer = PlateBlurrer()
        mock_detector = MagicMock()
        mock_detector.detect.return_value = []
        blurrer._detector = mock_detector

        try:
            blurrer.blur_plates(tmp_path, tmp_path)
            assert Path(tmp_path).exists()
            assert Path(tmp_path).stat().st_size > 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)
