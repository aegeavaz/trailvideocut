"""Tests for the Show Phone Filter checkbox wiring on the Review page.

Verifies:
- The checkbox is disabled when no phone zones are recorded or when Exclude
  Phone is off.
- The checkbox enables when Exclude Phone is on AND the current clip has zones.
- Toggling the checkbox pushes zones into the overlay.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtTest import QTest

from trailvideocut.plate.models import ClipPlateData, PlateBox
from trailvideocut.ui.review_page import ReviewPage


CURRENT_FRAME = 42
ZONES_ON_FRAME = [(0.10, 0.20, 0.30, 0.40)]


def _plate_data_with_zones() -> ClipPlateData:
    return ClipPlateData(
        clip_index=0,
        detections={
            CURRENT_FRAME: [
                PlateBox(x=0.55, y=0.60, w=0.15, h=0.08, confidence=0.9),
            ],
        },
        phone_zones={CURRENT_FRAME: ZONES_ON_FRAME},
    )


def _plate_data_no_zones() -> ClipPlateData:
    return ClipPlateData(
        clip_index=0,
        detections={
            CURRENT_FRAME: [
                PlateBox(x=0.55, y=0.60, w=0.15, h=0.08, confidence=0.9),
            ],
        },
    )


def _prime(page: ReviewPage, clip_data: ClipPlateData) -> None:
    page._plate_data[0] = clip_data
    page._plate_overlay.set_clip_data(clip_data)
    page._plate_overlay.set_current_frame(CURRENT_FRAME, force=True)
    page._timeline._selected = 0


@pytest.fixture
def review_page(qapp):
    page = ReviewPage()
    page.show()
    QTest.qWait(10)
    yield page
    page.close()
    page.deleteLater()
    QTest.qWait(10)


def test_checkbox_disabled_initially(review_page):
    """Fresh page has no zones yet, so the checkbox is gated off. The user
    preference defaults to checked so zones appear automatically the moment
    they become available (see `test_toggling_on_pushes_zones_to_overlay`).
    """
    assert review_page._chk_show_phone_filter.isEnabled() is False
    assert review_page._chk_show_phone_filter.isChecked() is True


def test_checkbox_disabled_when_no_zones(review_page):
    _prime(review_page, _plate_data_no_zones())
    assert review_page._chk_exclude_phones.isChecked() is True  # default on
    review_page._update_show_phone_filter_enabled()
    assert review_page._chk_show_phone_filter.isEnabled() is False


def test_checkbox_enabled_when_zones_and_exclude_phones_on(review_page):
    _prime(review_page, _plate_data_with_zones())
    review_page._chk_exclude_phones.setChecked(True)
    review_page._update_show_phone_filter_enabled()
    assert review_page._chk_show_phone_filter.isEnabled() is True


def test_checkbox_force_off_when_exclude_phones_unchecked(review_page):
    """When Exclude Phone turns off, the overlay must hide zones immediately.
    The checkbox's checked state is a user *preference* and is preserved so
    that re-enabling the feature later restores zone visibility without
    requiring another click.
    """
    _prime(review_page, _plate_data_with_zones())
    review_page._chk_show_phone_filter.setEnabled(True)
    review_page._chk_show_phone_filter.setChecked(True)
    review_page._plate_overlay.set_phone_zones_visible(True)

    review_page._chk_exclude_phones.setChecked(False)
    review_page._update_show_phone_filter_enabled()

    assert review_page._chk_show_phone_filter.isEnabled() is False
    # Preference preserved — not force-unchecked — so re-enabling restores state.
    assert review_page._chk_show_phone_filter.isChecked() is True
    assert review_page._plate_overlay._phone_zones_visible is False


def test_checkbox_default_on_pushes_zones_when_enabled(review_page):
    """Default is checked=True; when zones first become available and the
    checkbox enables, the overlay must immediately reflect the zones without
    requiring a user click.
    """
    _prime(review_page, _plate_data_with_zones())
    # Default checkbox state: checked=True, enabled=False.
    assert review_page._chk_show_phone_filter.isChecked() is True

    review_page._update_show_phone_filter_enabled()
    assert review_page._chk_show_phone_filter.isEnabled() is True
    assert review_page._plate_overlay._phone_zones_visible is True
    assert review_page._plate_overlay._phone_zones == ZONES_ON_FRAME


def test_toggling_off_hides_zones(review_page):
    _prime(review_page, _plate_data_with_zones())
    review_page._update_show_phone_filter_enabled()
    assert review_page._plate_overlay._phone_zones_visible is True

    review_page._chk_show_phone_filter.setChecked(False)
    assert review_page._plate_overlay._phone_zones_visible is False
