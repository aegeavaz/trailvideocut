"""Tests for VideoPlayer.seek_to's centre-of-frame targeting.

Clip-list clicks, mark jumps, and preview re-seeks all route through
``VideoPlayer.seek_to(seconds)``. The implementation MUST resolve the
seconds-valued argument to a source-frame index and drive ``_seek`` with
the centre of that frame's ideal window (``int((frame + 0.5) * 1000 / fps)``),
matching the formula ``_step_forward`` / ``_step_back`` use. Centre-of-window
targeting absorbs the container PTS offset that otherwise parks the decoder
on the previous frame.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from trailvideocut.ui.video_player import VideoPlayer


@pytest.fixture
def player(qapp):
    p = VideoPlayer()
    yield p
    p.deleteLater()


def _capture_seek(player: VideoPlayer) -> list[int]:
    calls: list[int] = []
    player._seek = lambda ms: calls.append(ms)  # type: ignore[method-assign]
    return calls


class TestSeekToCentreOfFrame:
    def test_seek_to_1_second_at_23_976_fps_targets_frame_23_centre(self, player):
        player._fps = 23.976
        player._duration_ms = 10_000
        calls = _capture_seek(player)

        player.seek_to(1.0)

        assert calls == [980]  # int((23 + 0.5) * 1000 / 23.976) = 980

    def test_seek_to_0_034s_at_29_97_fps_targets_frame_1_centre(self, player):
        player._fps = 29.97
        player._duration_ms = 10_000
        calls = _capture_seek(player)

        player.seek_to(0.034)

        assert calls == [50]  # int(1.5 * 1000 / 29.97) = 50, not 34

    def test_seek_to_zero_returns_frame_zero_clamp(self, player):
        player._fps = 29.97
        player._duration_ms = 10_000
        calls = _capture_seek(player)

        player.seek_to(0.0)

        assert calls == [0]

    def test_seek_to_clamps_to_duration(self, player):
        player._fps = 29.97
        player._duration_ms = 100
        calls = _capture_seek(player)

        player.seek_to(5.0)

        assert calls == [100]

    def test_seek_to_uses_position_to_frame_epsilon(self, player):
        """`seek_to(4.1)` at 30 fps MUST resolve to frame 123, not 122.

        Naive ``int(4.1 * 30)`` evaluates to 122 because of float drift
        (``4.1 * 30 = 122.9999…``). ``position_to_frame`` adds a 1e-9 epsilon
        to keep the round-trip exact. The resulting centre-of-frame target
        for frame 123 at 30 fps is ``int(123.5 * 1000 / 30)`` = 4116 ms,
        distinguishing it clearly from the wrong-frame value (4083 ms).
        """
        player._fps = 30.0
        player._duration_ms = 10_000
        calls = _capture_seek(player)

        player.seek_to(4.1)

        assert calls == [4116]

    def test_negative_seconds_clamps_to_zero(self, player):
        """Defensive: a negative value MUST NOT produce a negative frame."""
        player._fps = 30.0
        player._duration_ms = 10_000
        calls = _capture_seek(player)

        player.seek_to(-0.5)

        assert calls == [0]
