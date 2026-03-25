"""Tests for the license plate blurring feature."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np


def _make_plate_roi(
    width: int = 150,
    height: int = 40,
    bg_value: int = 240,
    char_value: int = 30,
    num_chars: int = 6,
) -> np.ndarray:
    """Create a synthetic grayscale plate-like ROI with evenly-spaced dark marks."""
    roi = np.full((height, width), bg_value, dtype=np.uint8)
    char_h = int(height * 0.55)
    char_w = max(2, int(width * 0.08))
    y_start = (height - char_h) // 2
    margin = int(width * 0.10)
    spacing = (width - 2 * margin) / max(num_chars, 1)
    for i in range(num_chars):
        x = int(margin + i * spacing)
        roi[y_start : y_start + char_h, x : x + char_w] = char_value
    return roi


class TestCharacterGridValidator:
    """Tests for CharacterGridValidator."""

    def test_accepts_plate_like_roi(self):
        """White ROI with 6 evenly-spaced dark rectangles is accepted."""
        from trailvideocut.editor.plate_blur import CharacterGridValidator

        validator = CharacterGridValidator()
        roi = _make_plate_roi(width=150, height=40, num_chars=6)
        # Embed ROI in a larger grayscale frame
        gray = np.full((200, 400), 60, dtype=np.uint8)
        gray[80:120, 100:250] = roi
        assert validator.has_characters(gray, (100, 80, 250, 120)) is True

    def test_rejects_uniform_white_roi(self):
        """Plain white ROI with no internal contours is rejected."""
        from trailvideocut.editor.plate_blur import CharacterGridValidator

        validator = CharacterGridValidator()
        gray = np.full((200, 400), 60, dtype=np.uint8)
        gray[80:120, 100:250] = 240  # uniform white
        assert validator.has_characters(gray, (100, 80, 250, 120)) is False

    def test_rejects_single_blob(self):
        """One large dark blob (not multiple characters) is rejected."""
        from trailvideocut.editor.plate_blur import CharacterGridValidator

        validator = CharacterGridValidator()
        gray = np.full((200, 400), 60, dtype=np.uint8)
        gray[80:120, 100:250] = 240
        # Single large dark blob
        gray[85:115, 140:210] = 30
        assert validator.has_characters(gray, (100, 80, 250, 120)) is False

    def test_rejects_random_noise(self):
        """Tiny scattered speckles are filtered out by size threshold."""
        from trailvideocut.editor.plate_blur import CharacterGridValidator

        validator = CharacterGridValidator()
        gray = np.full((200, 400), 240, dtype=np.uint8)
        # Scatter single dark pixels
        rng = np.random.RandomState(42)
        for _ in range(50):
            y = rng.randint(80, 120)
            x = rng.randint(100, 250)
            gray[y, x] = 30
        assert validator.has_characters(gray, (100, 80, 250, 120)) is False

    def test_rejects_vertically_scattered_blobs(self):
        """Correct-size blobs at random y-positions fail alignment check."""
        from trailvideocut.editor.plate_blur import CharacterGridValidator

        validator = CharacterGridValidator()
        # Use a taller ROI so vertical scatter is more pronounced
        gray = np.full((300, 400), 240, dtype=np.uint8)
        # 5 blobs scattered across full height of a 120px tall ROI
        y_positions = [82, 112, 152, 182, 92]
        for i, y in enumerate(y_positions):
            x = 110 + i * 25
            gray[y : y + 12, x : x + 6] = 30
        assert validator.has_characters(gray, (100, 80, 250, 200)) is False

    def test_rejects_inconsistent_heights(self):
        """Aligned blobs with wildly varying heights fail consistency check."""
        from trailvideocut.editor.plate_blur import CharacterGridValidator

        validator = CharacterGridValidator()
        gray = np.full((200, 400), 240, dtype=np.uint8)
        # 5 blobs at same y-center but very different heights
        heights = [4, 20, 6, 25, 3]
        for i, h in enumerate(heights):
            x = 110 + i * 25
            y = 100 - h // 2
            gray[y : y + h, x : x + 6] = 30
        assert validator.has_characters(gray, (100, 80, 250, 120)) is False

    def test_custom_min_char_count(self):
        """Configurable min_char_count threshold works."""
        from trailvideocut.editor.plate_blur import CharacterGridValidator

        roi = _make_plate_roi(width=150, height=40, num_chars=4)
        gray = np.full((200, 400), 60, dtype=np.uint8)
        gray[80:120, 100:250] = roi

        strict = CharacterGridValidator(min_char_count=5)
        assert strict.has_characters(gray, (100, 80, 250, 120)) is False

        lenient = CharacterGridValidator(min_char_count=3)
        assert lenient.has_characters(gray, (100, 80, 250, 120)) is True

    def test_small_roi_returns_false(self):
        """Very small ROI returns False without crashing."""
        from trailvideocut.editor.plate_blur import CharacterGridValidator

        validator = CharacterGridValidator()
        gray = np.full((100, 100), 200, dtype=np.uint8)
        assert validator.has_characters(gray, (10, 10, 20, 18)) is False


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
        # 38x26 white rect → aspect ~1.46 (within 1.2-1.6 filter)
        frame[180:206, 378:416] = 240
        # 5 dark character marks for contrast + character validation
        frame[184:198, 382:384] = 30
        frame[184:198, 387:389] = 30
        frame[184:198, 392:394] = 30
        frame[184:198, 397:399] = 30
        frame[184:198, 402:404] = 30

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

    def test_detect_rejects_white_rectangle_without_characters(self):
        """A plain white rectangle with no character marks is rejected."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        frame = np.full((400, 800, 3), 60, dtype=np.uint8)
        # White rectangle that passes shape/brightness but has no characters
        # Use gradient noise to pass contrast check (std >= 15)
        frame[180:206, 378:416] = 240
        # Add slight gradient so std > 15 but no character-like contours
        for col in range(378, 416):
            frame[180:206, col, :] = min(255, 220 + (col - 378))

        plates = detector.detect(frame)
        assert len(plates) == 0

    def test_detect_accepts_plate_with_characters(self):
        """White rectangle with evenly-spaced dark marks is detected."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        frame = np.full((400, 800, 3), 60, dtype=np.uint8)
        # 38x26 white rect with 5 character marks
        frame[180:206, 378:416] = 240
        frame[184:198, 382:384] = 30
        frame[184:198, 387:389] = 30
        frame[184:198, 392:394] = 30
        frame[184:198, 397:399] = 30
        frame[184:198, 402:404] = 30

        plates = detector.detect(frame)
        assert len(plates) >= 1

    def test_detector_accepts_custom_validator(self):
        """PlateShapeDetector accepts injected validator via DI."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        mock_validator = MagicMock()
        mock_validator.has_characters.return_value = True
        detector = PlateShapeDetector(validator=mock_validator)

        frame = np.full((400, 800, 3), 60, dtype=np.uint8)
        frame[180:206, 378:416] = 240
        # Add contrast marks so it passes _find_plates
        frame[184:198, 390:400] = 30

        detector.detect(frame)
        # Validator was called for each candidate
        assert mock_validator.has_characters.called

    def test_excludes_detection_in_bottom_center(self):
        """Plate in the bottom-center exclusion zone is discarded."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        frame = np.full((400, 800, 3), 60, dtype=np.uint8)
        # Place plate at bottom center: cy≈355, cx≈400 (both in exclusion zone)
        frame[342:368, 381:419] = 240
        frame[348:362, 385:387] = 30
        frame[348:362, 390:392] = 30
        frame[348:362, 395:397] = 30
        frame[348:362, 400:402] = 30
        frame[348:362, 405:407] = 30

        plates = detector.detect(frame)
        assert len(plates) == 0

    def test_keeps_detection_in_bottom_left(self):
        """Plate in bottom-left (outside horizontal middle third) is kept."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        frame = np.full((400, 800, 3), 60, dtype=np.uint8)
        # Place plate at bottom left: cy≈355, cx≈100 (left of middle third)
        frame[342:368, 81:119] = 240
        frame[348:362, 85:87] = 30
        frame[348:362, 90:92] = 30
        frame[348:362, 95:97] = 30
        frame[348:362, 100:102] = 30
        frame[348:362, 105:107] = 30

        plates = detector.detect(frame)
        assert len(plates) >= 1

    def test_keeps_detection_in_top_center(self):
        """Plate in top-center (outside bottom 15%) is kept."""
        from trailvideocut.editor.plate_blur import PlateShapeDetector

        detector = PlateShapeDetector()
        frame = np.full((400, 800, 3), 60, dtype=np.uint8)
        # Place plate at top center: cy≈50, cx≈400
        frame[37:63, 381:419] = 240
        frame[43:57, 385:387] = 30
        frame[43:57, 390:392] = 30
        frame[43:57, 395:397] = 30
        frame[43:57, 400:402] = 30
        frame[43:57, 405:407] = 30

        plates = detector.detect(frame)
        assert len(plates) >= 1


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
        mock_gap_filler = MagicMock()
        # flush() returns one result per push; flush_all() returns nothing
        mock_gap_filler.flush.return_value = [([(30, 20, 150, 60)], False)]
        mock_gap_filler.flush_all.return_value = []
        blurrer._gap_filler = mock_gap_filler

        progress_calls = []

        try:
            blurrer.blur_plates(
                tmp_path,
                output_path,
                progress_callback=lambda cur, tot: progress_calls.append((cur, tot)),
            )

            assert Path(output_path).exists()
            assert len(progress_calls) == 5
            assert mock_gap_filler.push.call_count == 5
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
        mock_gap_filler = MagicMock()
        mock_gap_filler.flush.return_value = [([], False)]
        mock_gap_filler.flush_all.return_value = []
        blurrer._gap_filler = mock_gap_filler

        try:
            blurrer.blur_plates(tmp_path, tmp_path)
            assert Path(tmp_path).exists()
            assert Path(tmp_path).stat().st_size > 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestPlateGapFiller:
    """Tests for PlateGapFiller with interpolation."""

    def _collect(self, filler, detections):
        """Push a sequence of detections and collect all flushed results."""
        frame = np.zeros((200, 300, 3), dtype=np.uint8)
        detector = filler._detector
        results = []
        for det in detections:
            detector.detect.return_value = det
            filler.push(frame)
            results.extend(filler.flush())
        results.extend(filler.flush_all())
        return results

    def test_returns_detections_directly(self):
        """When detector finds plates, those are returned not interpolated."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        plates = [(100, 100, 130, 120)]
        filler = PlateGapFiller(detector, max_gap=3)

        results = self._collect(filler, [plates, plates])
        assert len(results) == 2
        for p, is_interp in results:
            assert p == plates
            assert is_interp is False

    def test_interpolates_gap(self):
        """Gap frames get linearly interpolated positions."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        filler = PlateGapFiller(detector, max_gap=3)

        # Detection → 2 misses → detection (plate moves 8px right)
        seq = [
            [(100, 100, 130, 120)],  # frame 0
            [],                       # frame 1 (gap)
            [],                       # frame 2 (gap)
            [(108, 100, 138, 120)],  # frame 3
        ]
        results = self._collect(filler, seq)
        assert len(results) == 4

        # Frame 0: real detection
        assert results[0] == ([(100, 100, 130, 120)], False)
        # Frame 3: real detection
        assert results[3] == ([(108, 100, 138, 120)], False)
        # Frames 1-2: interpolated, marked True
        assert results[1][1] is True
        assert results[2][1] is True
        # Check interpolated x1: should be ~102 and ~105
        assert results[1][0][0][0] in range(101, 104)  # ~102
        assert results[2][0][0][0] in range(104, 107)  # ~105

    def test_extended_gap_coherent_interpolated(self):
        """Long gap with coherent endpoints is interpolated immediately."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        filler = PlateGapFiller(detector, max_gap=2, extended_gap=10, max_distance=150)

        seq = [
            [(100, 100, 130, 120)],  # frame 0
            [], [], [], [], [],       # 5 misses (> max_gap=2, ≤ extended_gap=10)
            [(112, 100, 142, 120)],  # frame 6 (coherent, dist=12)
        ]
        results = self._collect(filler, seq)
        assert len(results) == 7
        # Frame 0: real
        assert results[0][1] is False
        # Frames 1-5: interpolated
        for i in range(1, 6):
            assert results[i][1] is True
            assert len(results[i][0]) == 1
        # Interpolated x1 should progress from 100 toward 112
        assert results[1][0][0][0] == 102  # t=1/6
        assert results[5][0][0][0] == 110  # t=5/6
        # Frame 6: real detection
        assert results[6][1] is False

    def test_extended_gap_incoherent_not_interpolated(self):
        """Long gap with incoherent endpoints is not interpolated."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        filler = PlateGapFiller(detector, max_gap=2, extended_gap=10, max_distance=100)

        seq = [
            [(100, 100, 130, 120)],
            [], [], [],               # 3 misses > max_gap
            [(900, 900, 930, 920)],  # far from prev (dist > 100)
        ]
        results = self._collect(filler, seq)
        assert len(results) == 5
        # Gap frames should be empty (endpoints not coherent)
        assert results[1][0] == []
        assert results[2][0] == []
        assert results[3][0] == []

    def test_exceeds_extended_gap(self):
        """Gap longer than extended_gap is emitted as empty."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        filler = PlateGapFiller(detector, max_gap=2, extended_gap=4)

        seq = [
            [(100, 100, 130, 120)],
            [], [], [], [], [],  # 5 misses > extended_gap=4
            [(120, 100, 150, 120)],
        ]
        results = self._collect(filler, seq)
        assert len(results) == 7
        for i in range(1, 6):
            assert results[i][0] == []

    def test_no_hallucination_without_prior_detection(self):
        """No interpolation if there was never a detection."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        filler = PlateGapFiller(detector, max_gap=3)

        results = self._collect(filler, [[], [], [], []])
        assert len(results) == 4
        for p, is_interp in results:
            assert p == []
            assert is_interp is False

    def test_trailing_gap_carries_forward(self):
        """At end of video, trailing gap frames carry forward last detection."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        filler = PlateGapFiller(detector, max_gap=3)

        seq = [
            [(100, 100, 130, 120)],
            [],  # trailing gap
            [],  # trailing gap
        ]
        results = self._collect(filler, seq)
        assert len(results) == 3
        assert results[0][1] is False
        # Trailing frames carry forward (marked as interpolated)
        assert results[1][0] == [(100, 100, 130, 120)]
        assert results[1][1] is True
        assert results[2][0] == [(100, 100, 130, 120)]
        assert results[2][1] is True

    def test_isolated_detection_overwritten_by_interpolation(self):
        """A false positive mid-gap is overwritten by gap interpolation."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        filler = PlateGapFiller(detector, max_gap=3, max_distance=100)

        seq = [
            [(100, 100, 130, 120)],   # frame 0: real
            [(100, 100, 130, 120)],   # frame 1: real
            [],                        # frame 2: gap (incoherent det at frame 3 keeps gap open)
            [(900, 900, 930, 920)],   # frame 3: false positive (incoherent, treated as gap)
            [],                        # frame 4: gap
            [(105, 105, 135, 125)],   # frame 5: real (coherent with frame 1 — closes gap)
            [(107, 106, 137, 126)],   # frame 6: real
        ]
        results = self._collect(filler, seq)
        assert len(results) == 7
        # Frames 2-4 are interpolated between frame 1 and 5 (false positive overwritten)
        assert results[2][1] is True
        assert results[3][1] is True  # false positive replaced with interpolation
        assert results[4][1] is True
        # Interpolated positions progress smoothly
        assert results[2][0][0][0] == 101  # x1 at t=1/4
        assert results[3][0][0][0] == 102  # x1 at t=2/4
        assert results[4][0][0][0] == 103  # x1 at t=3/4

    def test_coherent_detections_kept(self):
        """Consecutive detections at nearby positions are not filtered."""
        from trailvideocut.editor.plate_blur import PlateGapFiller, PlateShapeDetector

        detector = MagicMock(spec=PlateShapeDetector)
        filler = PlateGapFiller(detector, max_gap=3, max_distance=100)

        seq = [
            [(100, 100, 130, 120)],
            [(103, 101, 133, 121)],
            [(106, 102, 136, 122)],
        ]
        results = self._collect(filler, seq)
        assert len(results) == 3
        for p, _ in results:
            assert len(p) == 1  # all kept
