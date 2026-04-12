"""Tests for plate blur integration in VideoAssembler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trailvideocut.config import TrailVideoCutConfig
from trailvideocut.editor.assembler import VideoAssembler
from trailvideocut.editor.models import CutPlan, EditDecision
from trailvideocut.plate.models import ClipPlateData, PlateBox


@pytest.fixture
def config(tmp_path):
    return TrailVideoCutConfig(
        video_path=tmp_path / "source.mp4",
        audio_path=tmp_path / "audio.mp3",
        output_path=tmp_path / "output.mp4",
        output_fps=30.0,
    )


@pytest.fixture
def assembler(config):
    return VideoAssembler(config)


class TestPreprocessBlurSegments:
    def test_returns_none_list_when_no_plate_data(self, assembler):
        # Segments are now (start, dur, clip_index)
        segments = [(0.0, 2.0, 0)]
        result, fps, _ = assembler._preprocess_blur_segments(segments, None)
        assert result == [None]
        assert fps == 0.0

    def test_returns_none_list_when_blur_disabled(self, assembler):
        assembler.config.plate_blur_enabled = False
        plate_data = {
            0: ClipPlateData(clip_index=0, detections={5: [PlateBox(0.1, 0.2, 0.05, 0.03)]})
        }
        segments = [(0.0, 2.0, 0)]
        result, fps, _ = assembler._preprocess_blur_segments(segments, plate_data)
        assert result == [None]
        assert fps == 0.0

    def test_skips_segments_without_plate_data(self, assembler):
        # Only clip 1 has plates
        plate_data = {
            1: ClipPlateData(clip_index=1, detections={10: [PlateBox(0.1, 0.2, 0.05, 0.03)]})
        }
        # Segments carry their clip_index
        segments = [(0.0, 2.0, 0), (2.0, 2.0, 1)]

        with patch("cv2.VideoCapture") as mock_vc, \
             patch("trailvideocut.plate.blur.PlateBlurProcessor") as MockProc:
            mock_cap = MagicMock()
            # cv2.CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4, CAP_PROP_FPS=5
            mock_cap.get.side_effect = lambda prop: {3: 1920, 4: 1080, 5: 30.0}.get(prop, 0)
            mock_vc.return_value = mock_cap

            mock_instance = MagicMock()
            mock_instance.process_segment.return_value = (Path("/tmp/blurred.avi"), 60)
            MockProc.return_value = mock_instance

            result, fps, _ = assembler._preprocess_blur_segments(segments, plate_data)

        assert result[0] is None  # segment 0 (clip 0) has no plates
        assert result[1] is not None  # segment 1 (clip 1) was processed
        assert fps == 30.0

    def test_clip_index_mapping_with_skipped_segments(self, assembler):
        """When a segment is skipped (dur < 0.05), clip_index still maps correctly."""
        # Clip 0 skipped, clip 1 no plates, clip 2 has plates
        plate_data = {
            2: ClipPlateData(clip_index=2, detections={100: [PlateBox(0.1, 0.2, 0.05, 0.03)]})
        }
        # After skipping clip 0, segments are (clip 1, clip 2)
        segments = [(1.0, 2.0, 1), (3.0, 2.0, 2)]

        with patch("cv2.VideoCapture") as mock_vc, \
             patch("trailvideocut.plate.blur.PlateBlurProcessor") as MockProc:
            mock_cap = MagicMock()
            mock_cap.get.side_effect = lambda prop: {3: 1920, 4: 1080, 5: 30.0}.get(prop, 0)
            mock_vc.return_value = mock_cap

            mock_instance = MagicMock()
            mock_instance.process_segment.return_value = (Path("/tmp/blurred.avi"), 60)
            MockProc.return_value = mock_instance

            result, fps, _ = assembler._preprocess_blur_segments(segments, plate_data)

        assert result[0] is None  # segment 0 is clip 1, no plates
        assert result[1] is not None  # segment 1 is clip 2, has plates
        assert fps == 30.0


class TestAssembleBlurRouting:
    """Tests that blur export routes through FFmpeg with PlateBlurProcessor."""

    def test_ffmpeg_hardcut_called_with_plate_data(self, assembler):
        """When blur is active + hard_cut, assemble calls FFmpeg hardcut with plate_data."""
        plate_data = {
            0: ClipPlateData(clip_index=0, detections={5: [PlateBox(0.1, 0.2, 0.05, 0.03)]})
        }
        plan = CutPlan(
            decisions=[EditDecision(beat_index=0, source_start=0.0, source_end=2.0,
                                    target_start=0.0, target_end=2.0, interest_score=1.0)],
            total_duration=2.0, song_tempo=120.0, transition_style="hard_cut",
        )

        with patch.object(assembler, "_resolve_fps"), \
             patch.object(assembler, "_assemble_ffmpeg_hardcut") as mock_hc, \
             patch.object(assembler, "_cleanup_blur_temps"):
            assembler.assemble(plan, plate_data=plate_data)

        mock_hc.assert_called_once_with(plan, plate_data)

    def test_ffmpeg_xfade_called_with_plate_data(self, assembler):
        """When blur is active + crossfade (>1 clip), assemble calls FFmpeg xfade with plate_data."""
        plate_data = {
            0: ClipPlateData(clip_index=0, detections={5: [PlateBox(0.1, 0.2, 0.05, 0.03)]})
        }
        plan = CutPlan(
            decisions=[
                EditDecision(beat_index=0, source_start=0.0, source_end=2.0,
                             target_start=0.0, target_end=2.0, interest_score=1.0),
                EditDecision(beat_index=1, source_start=3.0, source_end=5.0,
                             target_start=2.0, target_end=4.0, interest_score=1.0),
            ],
            total_duration=4.0, song_tempo=120.0, transition_style="crossfade",
            crossfade_duration=0.5,
        )

        with patch.object(assembler, "_resolve_fps"), \
             patch.object(assembler, "_assemble_ffmpeg_xfade") as mock_xf, \
             patch.object(assembler, "_cleanup_blur_temps"):
            assembler.assemble(plan, plate_data=plate_data)

        mock_xf.assert_called_once_with(plan, plate_data)

    def test_moviepy_fallback_receives_plate_data(self, assembler):
        """When FFmpeg fails with blur active, MoviePy fallback receives plate_data."""
        plate_data = {
            0: ClipPlateData(clip_index=0, detections={5: [PlateBox(0.1, 0.2, 0.05, 0.03)]})
        }
        plan = CutPlan(
            decisions=[EditDecision(beat_index=0, source_start=0.0, source_end=2.0,
                                    target_start=0.0, target_end=2.0, interest_score=1.0)],
            total_duration=2.0, song_tempo=120.0, transition_style="hard_cut",
        )

        with patch.object(assembler, "_resolve_fps"), \
             patch.object(assembler, "_assemble_ffmpeg_hardcut", side_effect=RuntimeError("fail")), \
             patch.object(assembler, "_assemble_moviepy") as mock_mp, \
             patch.object(assembler, "_cleanup_blur_temps"):
            assembler.assemble(plan, plate_data=plate_data)

        mock_mp.assert_called_once_with(plan, plate_data)

    def test_standard_path_without_blur(self, assembler):
        """When no plate data, standard export path is used."""
        plan = CutPlan(
            decisions=[EditDecision(beat_index=0, source_start=0.0, source_end=2.0,
                                    target_start=0.0, target_end=2.0, interest_score=1.0)],
            total_duration=2.0, song_tempo=120.0, transition_style="hard_cut",
        )

        with patch.object(assembler, "_resolve_fps"), \
             patch.object(assembler, "_assemble_moviepy") as mock_mp, \
             patch.object(assembler, "_assemble_ffmpeg_hardcut", side_effect=RuntimeError("fallback")), \
             patch.object(assembler, "_cleanup_blur_temps"):
            assembler.assemble(plan, plate_data=None)

        mock_mp.assert_called_once()
        # Called with no plate_data (fallback path)
        call_kwargs = mock_mp.call_args
        assert call_kwargs == ((plan, None),) or call_kwargs == ((plan,), {})


class TestProbeRationalFps:
    """Tests for _probe_rational_fps()."""

    def test_parses_rational_tbr(self, assembler):
        """Parses '24000/1001 tbr' from FFmpeg output."""
        stderr = "Stream #0:0: Video: h264, 1920x1080, 24000/1001 tbr"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stderr=stderr)
            result = assembler._probe_rational_fps(23.976)
        assert result == "24000/1001"

    def test_maps_decimal_to_standard_rational(self, assembler):
        """Maps '29.97 tbr' to '30000/1001'."""
        stderr = "Stream #0:0: Video: h264, 1920x1080, 29.97 tbr"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stderr=stderr)
            result = assembler._probe_rational_fps(29.97)
        assert result == "30000/1001"

    def test_fallback_on_probe_failure(self, assembler):
        """Falls back to str(source_fps) when FFmpeg fails."""
        with patch("subprocess.run", side_effect=RuntimeError("no ffmpeg")):
            result = assembler._probe_rational_fps(25.0)
        assert result == "25.0"
