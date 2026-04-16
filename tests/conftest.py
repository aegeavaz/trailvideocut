import os

# Ensure Qt can run without a display in CI / headless dev environments.
# Must be set BEFORE any PySide6 import happens in tests or the app code.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from trailvideocut.audio.models import AudioAnalysis, BeatInfo, MusicSection
from trailvideocut.video.models import InterestScore, VideoSegment


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for widget tests.

    Skips the test if PySide6 is not installed (the `ui` extras are optional).
    """
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_beats() -> list[BeatInfo]:
    """Generate 10 beats at 120 BPM (0.5s apart)."""
    return [
        BeatInfo(timestamp=i * 0.5, strength=0.8 if i % 4 == 0 else 0.5, is_downbeat=i % 4 == 0)
        for i in range(10)
    ]


@pytest.fixture
def sample_audio_analysis(sample_beats) -> AudioAnalysis:
    """A minimal AudioAnalysis for testing."""
    return AudioAnalysis(
        duration=5.0,
        tempo=120.0,
        beats=sample_beats,
        sections=[
            MusicSection(label="intro", start_time=0.0, end_time=2.0, energy=0.3),
            MusicSection(label="chorus", start_time=2.0, end_time=5.0, energy=0.9),
        ],
        onset_envelope=np.random.rand(100),
        sample_rate=22050,
    )


@pytest.fixture
def sample_segments() -> list[VideoSegment]:
    """Generate 40 overlapping video segments (2s window, 0.5s hop) over 20s."""
    segments = []
    t = 0.0
    while t < 20.0:
        interest = InterestScore(
            optical_flow=np.random.rand(),
            color_change=np.random.rand(),
            edge_variance=np.random.rand(),
            brightness_change=np.random.rand(),
        )
        segments.append(
            VideoSegment(
                start_time=t,
                end_time=min(t + 2.0, 20.0),
                interest=interest,
                scene_boundary_near=(int(t) % 5 == 0),
            )
        )
        t += 0.5
    return segments
