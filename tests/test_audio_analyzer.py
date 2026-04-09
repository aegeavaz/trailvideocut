from pathlib import Path


from trailvideocut.audio.models import BeatInfo
from trailvideocut.audio.analyzer import AudioAnalyzer
from trailvideocut.config import TrailVideoCutConfig


class TestBeatFiltering:
    """Test the beat filtering logic directly without requiring audio files."""

    def _make_analyzer(self, **overrides) -> AudioAnalyzer:
        defaults = dict(video_path=Path("test.mp4"), audio_path=Path("test.wav"))
        defaults.update(overrides)
        config = TrailVideoCutConfig(**defaults)
        return AudioAnalyzer(config)

    def test_filters_beats_too_close(self):
        analyzer = self._make_analyzer(beat_proximity_threshold=0.25)
        beats = [
            BeatInfo(timestamp=0.0, strength=0.5, is_downbeat=True),
            BeatInfo(timestamp=0.1, strength=0.3, is_downbeat=False),  # too close, skip
            BeatInfo(timestamp=0.5, strength=0.5, is_downbeat=False),
        ]
        filtered = analyzer._filter_beats(beats)
        assert len(filtered) == 2
        assert filtered[0].timestamp == 0.0
        assert filtered[1].timestamp == 0.5

    def test_replaces_with_stronger_downbeat(self):
        analyzer = self._make_analyzer(beat_proximity_threshold=0.25)
        beats = [
            BeatInfo(timestamp=0.0, strength=0.3, is_downbeat=False),
            BeatInfo(timestamp=0.1, strength=0.9, is_downbeat=True),  # stronger, replaces
            BeatInfo(timestamp=0.5, strength=0.5, is_downbeat=False),
        ]
        filtered = analyzer._filter_beats(beats)
        assert len(filtered) == 2
        assert filtered[0].timestamp == 0.1  # replaced by stronger beat

    def test_inserts_synthetic_beats_for_long_gaps(self):
        analyzer = self._make_analyzer(max_segment_duration=4.0)
        beats = [
            BeatInfo(timestamp=0.0, strength=0.5, is_downbeat=True),
            BeatInfo(timestamp=10.0, strength=0.5, is_downbeat=True),  # 10s gap
        ]
        filtered = analyzer._filter_beats(beats)
        # Should insert sub-beats to break up the 10s gap
        assert len(filtered) > 2
        # All gaps should be <= max_segment_duration
        for i in range(1, len(filtered)):
            gap = filtered[i].timestamp - filtered[i - 1].timestamp
            assert gap <= 4.0 + 0.01  # small tolerance

    def test_empty_beats(self):
        analyzer = self._make_analyzer()
        assert analyzer._filter_beats([]) == []

    def test_single_beat(self):
        analyzer = self._make_analyzer()
        beats = [BeatInfo(timestamp=0.0, strength=0.5)]
        filtered = analyzer._filter_beats(beats)
        assert len(filtered) == 1
