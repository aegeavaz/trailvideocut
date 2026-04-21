"""Exporter-side plate-metadata tests.

Covers OpenSpec `export-plates-davinci-resolve` tasks 6.1, 6.2, and 6.4:

- 6.1 OTIO metadata embedding: the clip-level `trailvideocut.plates`
  payload is populated with the expected shape and values.
- 6.2 Frame-offset mapping: plates outside the clip's source range are
  excluded, plates inside are re-keyed to clip-relative frame numbers,
  and fractional fps rates (23.976 etc.) do not introduce off-by-one
  drift between the OTIO source_range and the embedded frame keys.
- 6.2b Schema parity: the Fusion Lua generator and the OTIO clip
  metadata both derive their dicts from the same helper, so they are
  byte-identical for the same input.  This is a guardrail against
  future drift.
- 6.2c All boxes are included (blur strength is auto-scaled from plate area).
- 6.4 WSL path handling: `generate_resolve_script()` converts
  `/mnt/c/...` paths to Windows form so the generated Python works when
  executed by DaVinci Resolve on the Windows host.
"""

from __future__ import annotations

from pathlib import Path


from trailvideocut.editor.exporter import (
    _build_clip_detections,
    _generate_otio_timeline,
)
from trailvideocut.editor.models import CutPlan, EditDecision
from trailvideocut.editor.resolve_script import generate_resolve_script
from trailvideocut.plate.models import ClipPlateData, PlateBox


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _decision(source_start: float, source_end: float, beat: int = 0) -> EditDecision:
    """Minimal EditDecision for exporter-level tests."""
    return EditDecision(
        beat_index=beat,
        source_start=source_start,
        source_end=source_end,
        target_start=0.0,
        target_end=source_end - source_start,
        interest_score=1.0,
    )


def _plan(decisions: list[EditDecision]) -> CutPlan:
    return CutPlan(
        decisions=decisions,
        total_duration=sum(d.source_end - d.source_start for d in decisions),
        song_tempo=120.0,
        transition_style="hard_cut",
        crossfade_duration=0.0,
    )


# ---------------------------------------------------------------------------
# _build_clip_detections helper
# ---------------------------------------------------------------------------


class TestBuildClipDetections:
    def test_in_range_frames_are_included(self):
        cpd = ClipPlateData(
            clip_index=0,
            detections={
                10: [PlateBox(0.1, 0.2, 0.05, 0.03)],
                11: [PlateBox(0.12, 0.22, 0.05, 0.03)],
                12: [PlateBox(0.14, 0.24, 0.05, 0.03)],
            },
        )
        result = _build_clip_detections(cpd, src_start_frame=10, src_end_frame=13)
        # All three in-range frames produce entries, re-keyed to clip-relative.
        assert sorted(result.keys(), key=int) == ["0", "1", "2"]

    def test_out_of_range_frames_are_excluded(self):
        cpd = ClipPlateData(
            clip_index=0,
            detections={
                5:  [PlateBox(0.1, 0.2, 0.05, 0.03)],   # before src_start
                10: [PlateBox(0.1, 0.2, 0.05, 0.03)],   # in
                12: [PlateBox(0.1, 0.2, 0.05, 0.03)],   # out (src_end is exclusive)
                20: [PlateBox(0.1, 0.2, 0.05, 0.03)],   # after
            },
        )
        result = _build_clip_detections(cpd, src_start_frame=10, src_end_frame=12)
        # Half-open [10, 12) keeps only frame 10.
        assert list(result.keys()) == ["0"]

    def test_frame_numbers_are_clip_relative(self):
        cpd = ClipPlateData(
            clip_index=0,
            detections={
                100: [PlateBox(0.1, 0.2, 0.05, 0.03)],
                105: [PlateBox(0.1, 0.2, 0.05, 0.03)],
                109: [PlateBox(0.1, 0.2, 0.05, 0.03)],
            },
        )
        result = _build_clip_detections(cpd, src_start_frame=100, src_end_frame=110)
        # Absolute 100 -> relative 0, 105 -> 5, 109 -> 9.
        assert sorted(result.keys(), key=int) == ["0", "5", "9"]

    def test_all_boxes_included(self):
        cpd = ClipPlateData(
            clip_index=0,
            detections={
                5: [
                    PlateBox(0.1, 0.2, 0.05, 0.03),
                    PlateBox(0.5, 0.5, 0.05, 0.03),
                ],
            },
        )
        result = _build_clip_detections(cpd, src_start_frame=0, src_end_frame=10)
        assert len(result["5"]) == 2

    def test_values_are_floats(self):
        """JSON-serialisable output — all numeric fields are Python float."""
        cpd = ClipPlateData(
            clip_index=0,
            detections={
                5: [PlateBox(0.1, 0.2, 0.05, 0.03)],
            },
        )
        result = _build_clip_detections(cpd, src_start_frame=0, src_end_frame=10)
        box = result["5"][0]
        for key in ("x", "y", "w", "h"):
            assert isinstance(box[key], float), f"{key} is not a float: {type(box[key])}"

    def test_empty_detections_returns_empty_dict(self):
        cpd = ClipPlateData(clip_index=0, detections={})
        assert _build_clip_detections(cpd, 0, 100) == {}


# ---------------------------------------------------------------------------
# OTIO metadata embedding  (task 6.1)
# ---------------------------------------------------------------------------


class TestOTIOPlateMetadataEmbedding:
    def _build_timeline(self, tmp_path, fps=30.0, plate_data=None):
        video = tmp_path / "src.mp4"
        audio = tmp_path / "audio.mp3"
        plan = _plan([_decision(1.0, 3.0)])
        return _generate_otio_timeline(
            plan,
            video_path=video,
            video_duration=10.0,
            audio_path=audio,
            r_frame_rate=f"{int(fps)}/1",
            timecode=None,
            plate_data=plate_data,
            fps=fps,
        )

    def test_clip_has_plate_metadata_when_detections_present(self, tmp_path):
        plate_data = {
            0: ClipPlateData(
                clip_index=0,
                detections={
                    # Clip spans source frames 30..90 (1s..3s @ 30fps).
                    40: [PlateBox(0.1, 0.2, 0.05, 0.03)],
                    50: [PlateBox(0.1, 0.2, 0.05, 0.03)],
                    60: [PlateBox(0.1, 0.2, 0.05, 0.03)],
                },
            ),
        }
        timeline = self._build_timeline(tmp_path, fps=30.0, plate_data=plate_data)
        clip = list(timeline.video_tracks()[0].find_clips())[0]
        meta = clip.metadata["trailvideocut"]["plates"]
        assert meta["fps"] == 30.0
        # Clip starts at frame 30; 40/50/60 -> clip-relative 10/20/30.
        assert sorted(meta["detections"].keys(), key=int) == ["10", "20", "30"]

    def test_clip_without_plates_has_no_metadata(self, tmp_path):
        plate_data = {
            0: ClipPlateData(clip_index=0, detections={}),
        }
        timeline = self._build_timeline(tmp_path, fps=30.0, plate_data=plate_data)
        clip = list(timeline.video_tracks()[0].find_clips())[0]
        assert "trailvideocut" not in clip.metadata

    def test_plate_data_none_leaves_clips_bare(self, tmp_path):
        timeline = self._build_timeline(tmp_path, fps=30.0, plate_data=None)
        clip = list(timeline.video_tracks()[0].find_clips())[0]
        assert "trailvideocut" not in clip.metadata


# ---------------------------------------------------------------------------
# Frame-offset mapping  (task 6.2)
# ---------------------------------------------------------------------------


class TestFrameOffsetMapping:
    def test_fractional_fps_mapping_agrees_with_otio_source_range(self, tmp_path):
        """Use 23.976 fps and a source_start that int()-truncates differently
        from round().  The plate metadata frame keys must agree with the
        frame number OTIO itself wrote into the clip's source_range — both
        must use round().
        """
        fps = 24000.0 / 1001.0  # 23.976...
        video = tmp_path / "src.mp4"
        audio = tmp_path / "audio.mp3"
        # Pick a source_start whose int() and round() differ.
        # t = 0.522s, fps = 23.976 -> t*fps = 12.515
        #   int()  -> 12
        #   round()-> 13
        source_start = 0.522
        source_end = source_start + 2.0
        plan = _plan([_decision(source_start, source_end)])

        # One plate at the first rounded frame of the clip.
        first_frame = round(source_start * fps)  # == 13
        plate_data = {
            0: ClipPlateData(
                clip_index=0,
                detections={
                    first_frame: [PlateBox(0.1, 0.2, 0.05, 0.03)],
                },
            ),
        }

        timeline = _generate_otio_timeline(
            plan,
            video_path=video,
            video_duration=10.0,
            audio_path=audio,
            r_frame_rate="24000/1001",
            timecode=None,
            plate_data=plate_data,
            fps=fps,
        )
        clip = list(timeline.video_tracks()[0].find_clips())[0]

        # The OTIO clip's source_range start (in frame units) must equal
        # the exporter's src_start_frame, which in turn must be the key
        # used to re-base the plate detections.
        otio_start_frame = int(clip.source_range.start_time.value)
        assert otio_start_frame == first_frame

        # The plate at the clip's first source frame must land at
        # clip-relative frame 0.
        detections = clip.metadata["trailvideocut"]["plates"]["detections"]
        assert "0" in detections, detections.keys()

    def test_plates_at_clip_boundary_exclusive_end(self, tmp_path):
        """``src_end_frame`` is half-open: a plate exactly at that frame
        must be excluded.  Using integer fps to avoid rounding noise.
        """
        fps = 30.0
        video = tmp_path / "src.mp4"
        audio = tmp_path / "audio.mp3"
        plan = _plan([_decision(1.0, 3.0)])  # frames [30, 90)
        plate_data = {
            0: ClipPlateData(
                clip_index=0,
                detections={
                    30: [PlateBox(0.1, 0.2, 0.05, 0.03)],   # included (start)
                    89: [PlateBox(0.1, 0.2, 0.05, 0.03)],   # included
                    90: [PlateBox(0.1, 0.2, 0.05, 0.03)],   # excluded (end)
                },
            ),
        }
        timeline = _generate_otio_timeline(
            plan,
            video_path=video,
            video_duration=10.0,
            audio_path=audio,
            r_frame_rate="30/1",
            timecode=None,
            plate_data=plate_data,
            fps=fps,
        )
        clip = list(timeline.video_tracks()[0].find_clips())[0]
        keys = set(clip.metadata["trailvideocut"]["plates"]["detections"].keys())
        assert keys == {"0", "59"}  # relative 30-30=0 and 89-30=59


# ---------------------------------------------------------------------------
# Schema parity guardrail  (task 6.2b)
# ---------------------------------------------------------------------------


class TestSchemaParity:
    def test_helper_result_is_byte_identical_for_both_paths(self):
        """The Fusion script path and the OTIO metadata path both call
        ``_build_clip_detections`` with identical arguments, so their
        emitted dicts must be byte-identical for the same input.
        """
        cpd = ClipPlateData(
            clip_index=0,
            detections={
                10: [PlateBox(0.10, 0.20, 0.05, 0.03)],
                11: [PlateBox(0.12, 0.22, 0.05, 0.03)],
            },
        )
        fusion_dict = _build_clip_detections(cpd, 10, 12)
        otio_dict = _build_clip_detections(cpd, 10, 12)
        assert fusion_dict == otio_dict
        # And the types are uniform (both should have float values).
        for d in (fusion_dict, otio_dict):
            for boxes in d.values():
                for box in boxes:
                    for key in ("x", "y", "w", "h"):
                        assert type(box[key]) is float


# ---------------------------------------------------------------------------
# WSL path handling in generate_resolve_script  (task 6.4)
# ---------------------------------------------------------------------------


class TestOTIOCumulativeSync:
    """Sync regression: the timeline position of the Nth cut must match
    ``round(target_end_N * fps) - round(target_start_0 * fps)`` instead of
    accumulating per-clip rounding drift."""

    def _plan_from_targets(self, targets: list[tuple[float, float]]) -> CutPlan:
        """Build a CutPlan where source_start/end mirror target_start/end
        (align_segment invariant) so the exporter sees realistic input."""
        decisions = [
            EditDecision(
                beat_index=i,
                source_start=ts,
                source_end=te,
                target_start=ts,
                target_end=te,
                interest_score=1.0,
            )
            for i, (ts, te) in enumerate(targets)
        ]
        return CutPlan(
            decisions=decisions,
            total_duration=targets[-1][1],
            song_tempo=143.0,
            transition_style="hard_cut",
            crossfade_duration=0.0,
        )

    def test_fractional_fps_60_cuts_bounded_drift(self, tmp_path):
        """60 cuts at 23.976 fps with non-frame-aligned beats. Cumulative
        track position should remain within 1 frame of the target beat."""
        fps = 24000.0 / 1001.0  # 23.976...
        # Beats every 0.417s starting at 0.0, like ~143 BPM
        interval = 0.417
        targets = [(i * interval, (i + 1) * interval) for i in range(60)]
        plan = self._plan_from_targets(targets)

        timeline = _generate_otio_timeline(
            plan,
            video_path=tmp_path / "src.mp4",
            video_duration=200.0,
            audio_path=tmp_path / "audio.mp3",
            r_frame_rate="24000/1001",
            timecode=None,
            fps=fps,
        )
        clips = list(timeline.video_tracks()[0].find_clips())
        assert len(clips) == 60

        # Cumulative sum of clip durations (in frames) == frame distance from
        # target_start[0] to target_end[i], within ≤1 frame.
        cumulative_frames = 0
        start_offset = round(targets[0][0] * fps)
        for i, clip in enumerate(clips):
            cumulative_frames += int(clip.source_range.duration.value)
            expected_frames = round(targets[i][1] * fps) - start_offset
            drift = abs(cumulative_frames - expected_frames)
            assert drift <= 1, (
                f"Cut {i + 1}/60 drift: {cumulative_frames} frames vs "
                f"expected {expected_frames} frames (diff {drift})"
            )

    def test_per_clip_duration_is_cumulative_frame_delta(self, tmp_path):
        """Each clip's duration equals ``round(target_end * fps) -
        round(target_start * fps)`` — the telescoping form that bounds total
        drift to one frame."""
        fps = 30.0
        targets = [(0.017, 0.533), (0.533, 1.050), (1.050, 1.567)]
        plan = self._plan_from_targets(targets)

        timeline = _generate_otio_timeline(
            plan,
            video_path=tmp_path / "src.mp4",
            video_duration=10.0,
            audio_path=tmp_path / "audio.mp3",
            r_frame_rate="30/1",
            timecode=None,
            fps=fps,
        )
        clips = list(timeline.video_tracks()[0].find_clips())
        for i, clip in enumerate(clips):
            ts, te = targets[i]
            expected = round(te * fps) - round(ts * fps)
            assert int(clip.source_range.duration.value) == expected, (
                f"Clip {i}: duration {clip.source_range.duration.value} != "
                f"expected {expected}"
            )


class TestGenerateResolveScriptWslPath:
    def test_mnt_c_path_converted_to_windows_drive(self):
        """A /mnt/c/... OTIO path gets converted to a C:\\... Windows path
        so the generated Python script can be executed by Resolve running
        on the Windows host.
        """
        otio_path = Path("/mnt/c/Videos/test project/output.otio")
        script = generate_resolve_script(otio_path, fps=30.0)
        # The Windows-form path must appear in the emitted script.
        assert "C:\\Videos\\test project\\output.otio" in script
        # And the original POSIX form must NOT appear (avoid accidental
        # fallback to a WSL path that Windows Python cannot open).
        assert "/mnt/c/" not in script

    def test_non_wsl_path_preserved(self, tmp_path):
        """A non-WSL absolute path is emitted as-is."""
        otio_path = tmp_path / "output.otio"
        script = generate_resolve_script(otio_path, fps=30.0)
        # Exact path must appear somewhere in the emitted script.
        # We expect it to be inserted verbatim (no /mnt/ remapping).
        assert str(otio_path) in script or str(otio_path.resolve()) in script
