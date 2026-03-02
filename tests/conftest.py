import numpy as np
import pytest

from smartcut.audio.models import AudioAnalysis, BeatInfo, MusicSection
from smartcut.video.models import InterestScore, VideoSegment


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
    """Generate 20 video segments (1s each) with varying interest scores."""
    segments = []
    for i in range(20):
        interest = InterestScore(
            optical_flow=np.random.rand(),
            color_change=np.random.rand(),
            edge_variance=np.random.rand(),
            brightness_change=np.random.rand(),
        )
        segments.append(
            VideoSegment(
                start_time=float(i),
                end_time=float(i + 1),
                interest=interest,
                scene_boundary_near=(i % 5 == 0),
            )
        )
    return segments
