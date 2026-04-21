"""Tests for the Refine Clip/Frame Plates buttons on the Review page.

refine-plate-box-fit / group 7.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.editor.models import EditDecision
from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.plate_refine_dialog import (
    PlateRefineReviewDialog,
    RefinementEntry,
)
from trailvideocut.ui.review_page import ReviewPage


def _make_page_with_clip(qapp, plate_data=None) -> ReviewPage:
    page = ReviewPage()
    clip = EditDecision(
        beat_index=0,
        source_start=0.0, source_end=5.0,
        target_start=0.0, target_end=5.0,
        interest_score=1.0,
    )
    page._timeline.set_data([clip], video_duration=5.0)
    page._timeline.select_clip(0)
    page._video_path = "/fake.mp4"
    if plate_data is not None:
        page._plate_data = plate_data
    page._update_frame_buttons()
    return page


class TestButtonsExist:
    def test_both_buttons_in_action_row(self, qapp):
        page = ReviewPage()
        try:
            assert hasattr(page, "_btn_refine_clip_plates")
            assert hasattr(page, "_btn_refine_frame_plates")
            assert page._btn_refine_clip_plates.text() == "Refine Clip Plates"
            assert page._btn_refine_frame_plates.text() == "Refine Frame Plates"
        finally:
            page.close()

    def test_disabled_initially(self, qapp):
        page = ReviewPage()
        try:
            assert not page._btn_refine_clip_plates.isEnabled()
            assert not page._btn_refine_frame_plates.isEnabled()
        finally:
            page.close()


class TestEnablementMirrorsClear:
    def test_refine_clip_enabled_when_clip_has_any_box(self, qapp):
        plate_data = {
            0: ClipPlateData(
                clip_index=0,
                detections={42: [PlateBox(0.1, 0.2, 0.1, 0.05)]},
            ),
        }
        page = _make_page_with_clip(qapp, plate_data=plate_data)
        try:
            # Mirrors Clear Clip Plates.
            assert page._btn_clear_clip_plates.isEnabled() is True
            assert page._btn_refine_clip_plates.isEnabled() is True
        finally:
            page.close()

    def test_refine_clip_disabled_when_no_boxes(self, qapp):
        plate_data = {
            0: ClipPlateData(clip_index=0, detections={}),
        }
        page = _make_page_with_clip(qapp, plate_data=plate_data)
        try:
            assert page._btn_clear_clip_plates.isEnabled() is False
            assert page._btn_refine_clip_plates.isEnabled() is False
        finally:
            page.close()

    def test_clip_with_gaps_still_enables_refine(self, qapp):
        """Not every frame needs a box — any box anywhere in the clip is enough."""
        plate_data = {
            0: ClipPlateData(
                clip_index=0,
                detections={
                    10: [PlateBox(0.1, 0.2, 0.1, 0.05)],
                    # frame 11 deliberately empty
                    12: [PlateBox(0.2, 0.3, 0.1, 0.05)],
                },
            ),
        }
        page = _make_page_with_clip(qapp, plate_data=plate_data)
        try:
            assert page._btn_refine_clip_plates.isEnabled() is True
        finally:
            page.close()


class TestRefineFrameCollection:
    def test_collect_frame_targets_current_frame_only(self, qapp):
        plate_data = {
            0: ClipPlateData(
                clip_index=0,
                detections={
                    10: [PlateBox(0.1, 0.2, 0.1, 0.05)],
                    20: [
                        PlateBox(0.1, 0.2, 0.1, 0.05),
                        PlateBox(0.3, 0.3, 0.1, 0.05, manual=True),
                    ],
                },
            ),
        }
        page = _make_page_with_clip(qapp, plate_data=plate_data)
        try:
            # Pretend the player is at frame 20. frame_at uses fps which may
            # be 0 before a video is loaded; patch the player's frame_at.
            page._player.frame_at = lambda *_: 20
            targets = page._collect_refine_targets_frame()
            assert len(targets) == 1
            frame_no, pairs = targets[0]
            assert frame_no == 20
            assert [idx for idx, _ in pairs] == [0, 1]
            # Frame 10's boxes must not be in targets.
        finally:
            page.close()

    def test_collect_clip_targets_includes_all_frames(self, qapp):
        plate_data = {
            0: ClipPlateData(
                clip_index=0,
                detections={
                    10: [PlateBox(0.1, 0.2, 0.1, 0.05)],
                    20: [PlateBox(0.2, 0.3, 0.1, 0.05)],
                },
            ),
        }
        page = _make_page_with_clip(qapp, plate_data=plate_data)
        try:
            targets = page._collect_refine_targets_clip()
            frame_nos = sorted(f for f, _ in targets)
            assert frame_nos == [10, 20]
            total_boxes = sum(len(pairs) for _, pairs in targets)
            assert total_boxes == 2
        finally:
            page.close()


class TestReviewDialog:
    def test_accept_all_high_confidence_marks_expected_rows(self, qapp):
        entries = [
            RefinementEntry(
                frame_no=10, box_idx=0,
                before=PlateBox(0.1, 0.1, 0.1, 0.05),
                after=PlateBox(0.12, 0.11, 0.09, 0.045),
                confidence=0.9, method="aabb",
            ),
            RefinementEntry(
                frame_no=11, box_idx=0,
                before=PlateBox(0.1, 0.1, 0.1, 0.05),
                after=PlateBox(0.12, 0.11, 0.09, 0.045),
                confidence=0.5, method="aabb",
            ),
        ]
        dlg = PlateRefineReviewDialog(entries, high_confidence_threshold=0.8)
        try:
            dlg._accept_high_confidence()
            assert dlg._checkboxes[0].isChecked() is True
            assert dlg._checkboxes[1].isChecked() is False
            accepted = dlg.accepted_entries
            assert len(accepted) == 1
            assert accepted[0].frame_no == 10
        finally:
            dlg.close()

    def test_revert_all_clears_checks(self, qapp):
        entries = [
            RefinementEntry(
                frame_no=10, box_idx=0,
                before=PlateBox(0.1, 0.1, 0.1, 0.05),
                after=PlateBox(0.12, 0.11, 0.09, 0.045),
                confidence=0.9, method="aabb",
            ),
        ]
        dlg = PlateRefineReviewDialog(entries)
        try:
            dlg._accept_all()
            assert dlg._checkboxes[0].isChecked() is True
            dlg._revert_all()
            assert dlg._checkboxes[0].isChecked() is False
            assert dlg.accepted_entries == []
        finally:
            dlg.close()
