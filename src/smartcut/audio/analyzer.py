import numpy as np
import librosa

from smartcut.audio.models import AudioAnalysis, BeatInfo
from smartcut.config import SmartCutConfig


class AudioAnalyzer:
    """Analyze audio for beats, tempo, and onset strength."""

    def __init__(self, config: SmartCutConfig):
        self.config = config

    def analyze(self) -> AudioAnalysis:
        """Load audio, detect beats, compute onset strength."""
        y, sr = self._load_audio()
        tempo, beat_frames = self._detect_beats(y, sr)
        onset_env = self._compute_onset_envelope(y, sr)
        beats = self._build_beat_list(beat_frames, onset_env, sr)
        beats = self._filter_beats(beats)
        duration = librosa.get_duration(y=y, sr=sr)
        return AudioAnalysis(
            duration=duration,
            tempo=tempo,
            beats=beats,
            onset_envelope=onset_env,
            sample_rate=sr,
        )

    def _load_audio(self) -> tuple[np.ndarray, int]:
        """Load audio file, resampled to 22050 Hz mono."""
        y, sr = librosa.load(str(self.config.audio_path), sr=22050, mono=True)
        return y, sr

    def _detect_beats(self, y: np.ndarray, sr: int) -> tuple[float, np.ndarray]:
        """Detect tempo and beat frame positions using percussive separation."""
        _, y_percussive = librosa.effects.hpss(y)
        tempo, beat_frames = librosa.beat.beat_track(y=y_percussive, sr=sr)
        return float(np.atleast_1d(tempo)[0]), beat_frames

    def _compute_onset_envelope(self, y: np.ndarray, sr: int) -> np.ndarray:
        """Compute the onset strength envelope."""
        return librosa.onset.onset_strength(y=y, sr=sr)

    def _build_beat_list(
        self, beat_frames: np.ndarray, onset_env: np.ndarray, sr: int
    ) -> list[BeatInfo]:
        """Convert beat frames to BeatInfo objects with strength scores."""
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        # Clamp indices to valid range
        safe_frames = np.clip(beat_frames, 0, len(onset_env) - 1)
        strengths = onset_env[safe_frames]

        # Normalize strengths to 0-1
        max_strength = strengths.max()
        if max_strength > 0:
            strengths = strengths / max_strength

        beats = []
        for i, (t, s) in enumerate(zip(beat_times, strengths)):
            is_downbeat = (i % 4 == 0) or s > 0.8
            beats.append(BeatInfo(timestamp=float(t), strength=float(s), is_downbeat=is_downbeat))
        return beats

    def _filter_beats(self, beats: list[BeatInfo]) -> list[BeatInfo]:
        """Handle edge cases: very fast or very slow tempos."""
        if not beats:
            return beats

        min_dur = self.config.min_segment_duration
        max_dur = self.config.max_segment_duration

        filtered = [beats[0]]
        for i in range(1, len(beats)):
            gap = beats[i].timestamp - filtered[-1].timestamp

            if gap < min_dur:
                # Too fast — keep only if this beat is stronger
                if beats[i].is_downbeat and not filtered[-1].is_downbeat:
                    filtered[-1] = beats[i]
                continue

            if gap > max_dur:
                # Too slow — insert synthetic sub-beats
                n_sub = int(np.ceil(gap / max_dur))
                sub_interval = gap / n_sub
                base_t = filtered[-1].timestamp
                for j in range(1, n_sub):
                    synthetic_t = base_t + j * sub_interval
                    filtered.append(
                        BeatInfo(timestamp=synthetic_t, strength=0.3, is_downbeat=False)
                    )

            filtered.append(beats[i])
        return filtered
