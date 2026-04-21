"""Review page behaviour when the playhead sits in a clip's transition tail.

Covers the plate-clip-transition-tail capability: overlay sync preference,
button enablement inside the tail, and Add Plate storage attribution.

Every test sets up a 2-clip crossfade plan, selects clip 0, and manipulates
the playhead. The helper `_make_page_with_plan` wires the CutPlan onto the
page so the tail-frame helpers can resolve the effective window.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.config import TransitionStyle
from trailvideocut.editor.models import CutPlan, EditDecision
from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.review_page import ReviewPage


FPS = 30.0
CROSSFADE = 0.2  # seconds → 6 frames at 30 fps
# Clip 0: 0..4s  (frames 0..120, tail frames 120..125)
# Clip 1: 4..8s  (frames 120..240)
CLIP0 = EditDecision(
    beat_index=0, source_start=0.0, source_end=4.0,
    target_start=0.0, target_end=4.0, interest_score=1.0,
)
CLIP1 = EditDecision(
    beat_index=1, source_start=4.0, source_end=8.0,
    target_start=3.8, target_end=7.8, interest_score=0.9,
)


def _make_plan() -> CutPlan:
    return CutPlan(
        decisions=[CLIP0, CLIP1],
        total_duration=8.0,
        song_tempo=120.0,
        transition_style=TransitionStyle.CROSSFADE.value,
        crossfade_duration=CROSSFADE,
    )


def _make_page_with_plan(qapp, plate_data=None) -> ReviewPage:
    page = ReviewPage()
    plan = _make_plan()
    page._timeline.set_data(plan.decisions, video_duration=8.0)
    page._timeline.select_clip(0)
    page._video_path = "/fake.mp4"
    page._cut_plan = plan
    # The player's fps is 30.0 by default, matching our FPS constant.
    assert page._player.fps == FPS
    if plate_data is not None:
        page._plate_data = plate_data
    page._update_frame_buttons()
    return page


def _seek_to_frame(page: ReviewPage, frame: int) -> None:
    """Mimic a player seek by overriding frame_at and the underlying
    QMediaPlayer position so `self._player.current_time` returns the
    expected value. `current_time` is a read-only property, so we patch
    the underlying `self._player._player.position()` QMediaPlayer call.
    """
    seconds = frame / FPS
    page._player.frame_at = lambda *_: frame
    # `current_time` is `self._player.position() / 1000.0` on the underlying
    # QMediaPlayer. Stub the position call to return the desired ms.
    page._player._player.position = lambda: int(seconds * 1000)


class TestOverlaySyncPrefersSelectedClipInTail:
    def test_playhead_in_selected_tail_keeps_overlay_on_selected(self, qapp):
        # Clip 0 is selected. Seek into clip 0's tail (frame 123 of 120..126).
        # The overlay's active clip data SHALL remain clip 0's, not clip 1's.
        clip0_data = ClipPlateData(
            clip_index=0,
            detections={118: [PlateBox(0.40, 0.50, 0.10, 0.05, angle=10.0)]},
        )
        clip1_data = ClipPlateData(
            clip_index=1,
            detections={130: [PlateBox(0.60, 0.50, 0.10, 0.05)]},
        )
        page = _make_page_with_plan(qapp, plate_data={0: clip0_data, 1: clip1_data})
        try:
            _seek_to_frame(page, 123)
            page._sync_overlay_to_current_clip()
            # The overlay's bound clip data SHALL be clip 0's.
            assert page._plate_overlay._clip_data is clip0_data
        finally:
            page.close()

    def test_playhead_past_tail_falls_through_to_next_clip(self, qapp):
        # Clip 0 is selected but the playhead is deep inside clip 1's core
        # range (frame 150, which is past clip 0's tail end of 126).
        # The overlay SHALL bind to clip 1's data and buttons reflect clip 1,
        # while the timeline selection remains clip 0.
        clip0_data = ClipPlateData(
            clip_index=0, detections={50: [PlateBox(0.40, 0.50, 0.10, 0.05)]},
        )
        clip1_data = ClipPlateData(
            clip_index=1, detections={150: [PlateBox(0.60, 0.50, 0.10, 0.05)]},
        )
        page = _make_page_with_plan(qapp, plate_data={0: clip0_data, 1: clip1_data})
        try:
            _seek_to_frame(page, 150)
            page._sync_overlay_to_current_clip()
            assert page._plate_overlay._clip_data is clip1_data
            # Selection is sticky.
            assert page._timeline.selected_index == 0
        finally:
            page.close()


class TestButtonsInTail:
    def test_clear_and_refine_enabled_when_tail_frame_has_plate(self, qapp):
        clip0_data = ClipPlateData(
            clip_index=0,
            detections={123: [PlateBox(0.45, 0.50, 0.10, 0.05)]},
        )
        page = _make_page_with_plan(qapp, plate_data={0: clip0_data})
        try:
            _seek_to_frame(page, 123)
            page._update_frame_buttons()
            assert page._btn_clear_frame_plates.isEnabled() is True
            assert page._btn_refine_frame_plates.isEnabled() is True
            assert page._btn_detect_frame.isEnabled() is True
        finally:
            page.close()

    def test_clear_disabled_when_tail_frame_has_no_plate(self, qapp):
        # Playhead in tail but no plate at that frame (yet) — clear/refine
        # frame-scoped buttons SHALL be disabled while Add Plate / Detect
        # Frame SHALL stay enabled.
        clip0_data = ClipPlateData(
            clip_index=0,
            detections={50: [PlateBox(0.4, 0.5, 0.1, 0.05)]},  # elsewhere
        )
        page = _make_page_with_plan(qapp, plate_data={0: clip0_data})
        try:
            _seek_to_frame(page, 123)
            page._update_frame_buttons()
            assert page._btn_clear_frame_plates.isEnabled() is False
            assert page._btn_refine_frame_plates.isEnabled() is False
            # Add Plate button: enabled state managed by the "has any plate
            # data" path, not frame-scoped; enabled here because plate data
            # for clip 0 exists.
            assert page._btn_detect_frame.isEnabled() is True
        finally:
            page.close()


class TestAddPlateInTailOwnedByCurrentClip:
    def test_add_in_tail_stores_under_selected_clip_with_reference_angle(self, qapp):
        # Core reference at frame 118 with angle=10°. Add Plate at frame 123
        # (in the tail) — the new box SHALL be stored at clip 0's
        # detections[123] (NOT clip 1) and inherit angle=10°.
        clip0_data = ClipPlateData(
            clip_index=0,
            detections={118: [PlateBox(0.40, 0.50, 0.10, 0.05, angle=10.0)]},
        )
        clip1_data = ClipPlateData(clip_index=1, detections={})
        page = _make_page_with_plan(
            qapp, plate_data={0: clip0_data, 1: clip1_data},
        )
        try:
            # Show the overlay so _on_add_plate's visibility guard passes.
            page._plate_overlay.setVisible(True)
            _seek_to_frame(page, 123)
            page._sync_overlay_to_current_clip()
            # The overlay's "current frame" must reflect the new playhead.
            page._plate_overlay.set_current_frame(123, force=True)
            page._on_add_plate()
            # The new manual plate SHALL live on clip 0, frame 123.
            assert 123 in clip0_data.detections
            assert 123 not in clip1_data.detections
            new_box = clip0_data.detections[123][0]
            assert new_box.manual is True
            assert new_box.angle == pytest.approx(10.0)
        finally:
            page.close()
