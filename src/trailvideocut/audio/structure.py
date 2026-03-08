import numpy as np
import librosa

from trailvideocut.audio.models import MusicSection


class MusicalStructureAnalyzer:
    """Detect musical structure (intro/verse/chorus/bridge/outro) via multi-feature segmentation."""

    def analyze(
        self,
        audio_path: str,
        sr: int = 22050,
        y: np.ndarray | None = None,
        onset_envelope: np.ndarray | None = None,
    ) -> list[MusicSection]:
        """Segment the audio into structural sections.

        Parameters
        ----------
        audio_path : str
            Path to audio file (used if ``y`` is not provided).
        sr : int
            Sample rate.
        y : np.ndarray, optional
            Pre-loaded audio waveform.
        onset_envelope : np.ndarray, optional
            Pre-computed onset strength envelope.  Computed from ``y`` when not
            provided.
        """
        if y is None:
            y, sr = librosa.load(audio_path, sr=sr)
        duration = librosa.get_duration(y=y, sr=sr)

        if onset_envelope is None:
            onset_envelope = librosa.onset.onset_strength(y=y, sr=sr)

        # Multi-feature matrix for segmentation
        features = self._compute_features(y, sr, onset_envelope)

        # Number of sections — roughly one per 12 seconds
        n_sections = min(20, max(4, int(duration / 12)))

        # Agglomerative clustering on stacked features
        boundary_frames = librosa.segment.agglomerative(features, n_sections)
        boundary_times = librosa.frames_to_time(boundary_frames, sr=sr)

        # Clean up boundaries
        all_boundaries = self._deduplicate_boundaries(
            boundary_times.tolist(), duration
        )

        # Pre-compute energy components
        rms = librosa.feature.rms(y=y)[0]
        rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
        onset_times = librosa.frames_to_time(np.arange(len(onset_envelope)), sr=sr)
        spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        centroid_times = librosa.frames_to_time(np.arange(len(spectral_centroid)), sr=sr)

        # Build sections with composite energy
        raw_energies = []
        sections = []
        for i in range(len(all_boundaries) - 1):
            start, end = all_boundaries[i], all_boundaries[i + 1]
            raw = self._compute_section_energy(
                start, end, rms, rms_times,
                onset_envelope, onset_times,
                spectral_centroid, centroid_times,
            )
            raw_energies.append(raw)
            sections.append(MusicSection(
                label="",  # assigned after energy normalization
                start_time=start,
                end_time=end,
                energy=0.0,
            ))

        # Normalize and assign composite energy
        self._assign_composite_energy(sections, raw_energies)

        # Label based on position and normalized energy
        total = len(sections)
        for i, s in enumerate(sections):
            s.label = self._label_section(i, total, s.energy)

        return sections

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_features(
        y: np.ndarray, sr: int, onset_envelope: np.ndarray
    ) -> np.ndarray:
        """Build a (33, T) multi-feature matrix for segmentation.

        Features (all default hop_length=512 at sr=22050):
        - Chroma CQT        (12 dims) — harmony/pitch
        - MFCC               (13 dims) — timbre/texture
        - Spectral contrast  (7 dims)  — spectral energy distribution
        - Onset strength     (1 dim)   — rhythmic activity
        """
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)          # (12, T)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)       # (13, T)
        contrast = librosa.feature.spectral_contrast(y=y, sr=sr)  # (7, T)

        # Onset envelope is 1-D; match frame count of other features
        target_len = chroma.shape[1]
        if len(onset_envelope) >= target_len:
            onset_row = onset_envelope[:target_len].reshape(1, -1)
        else:
            onset_row = np.pad(
                onset_envelope, (0, target_len - len(onset_envelope))
            ).reshape(1, -1)

        # Stack and min-max normalize each row independently to [0, 1]
        stacked = np.vstack([chroma, mfcc, contrast, onset_row])  # (33, T)
        row_min = stacked.min(axis=1, keepdims=True)
        row_max = stacked.max(axis=1, keepdims=True)
        denom = row_max - row_min
        denom[denom == 0] = 1.0  # avoid division by zero for constant rows
        normalized = (stacked - row_min) / denom

        return normalized

    @staticmethod
    def _deduplicate_boundaries(
        boundary_times: list[float],
        duration: float,
        min_section_length: float = 2.0,
    ) -> list[float]:
        """Remove boundaries that create sections shorter than *min_section_length*.

        Guarantees first boundary = 0.0 and last = *duration*.
        """
        raw = sorted(set([0.0] + boundary_times + [duration]))

        # Forward pass: drop boundaries too close to the previous kept one
        kept: list[float] = [raw[0]]
        for b in raw[1:]:
            if b - kept[-1] >= min_section_length:
                kept.append(b)

        # Ensure last boundary is duration
        if kept[-1] != duration:
            if duration - kept[-1] < min_section_length and len(kept) > 1:
                kept[-1] = duration
            else:
                kept.append(duration)

        return kept

    @staticmethod
    def _compute_section_energy(
        start: float,
        end: float,
        rms: np.ndarray,
        rms_times: np.ndarray,
        onset_envelope: np.ndarray,
        onset_times: np.ndarray,
        spectral_centroid: np.ndarray,
        centroid_times: np.ndarray,
    ) -> tuple[float, float, float]:
        """Compute raw (rms_mean, onset_density, centroid_mean) for one section."""
        section_dur = end - start if end > start else 1.0

        # RMS energy — mean loudness
        rms_mask = (rms_times >= start) & (rms_times < end)
        rms_mean = float(np.mean(rms[rms_mask])) if rms_mask.any() else 0.0

        # Onset density — percussive events per second
        onset_mask = (onset_times >= start) & (onset_times < end)
        onset_sum = float(np.sum(onset_envelope[onset_mask])) if onset_mask.any() else 0.0
        onset_density = onset_sum / section_dur

        # Spectral centroid — brightness
        cent_mask = (centroid_times >= start) & (centroid_times < end)
        centroid_mean = float(np.mean(spectral_centroid[cent_mask])) if cent_mask.any() else 0.0

        return (rms_mean, onset_density, centroid_mean)

    @staticmethod
    def _assign_composite_energy(
        sections: list[MusicSection],
        raw_energies: list[tuple[float, float, float]],
    ) -> None:
        """Normalize each energy dimension to [0,1] then combine weighted.

        Weights: RMS 0.5, onset density 0.3, spectral centroid 0.2.
        """
        if not raw_energies:
            return

        rms_vals = np.array([e[0] for e in raw_energies])
        onset_vals = np.array([e[1] for e in raw_energies])
        centroid_vals = np.array([e[2] for e in raw_energies])

        def _normalize(arr: np.ndarray) -> np.ndarray:
            mn, mx = arr.min(), arr.max()
            if mx - mn == 0:
                return np.zeros_like(arr)
            return (arr - mn) / (mx - mn)

        rms_n = _normalize(rms_vals)
        onset_n = _normalize(onset_vals)
        centroid_n = _normalize(centroid_vals)

        composite = 0.5 * rms_n + 0.3 * onset_n + 0.2 * centroid_n

        # Re-normalize composite to span full [0, 1] range
        composite = _normalize(composite)

        for section, energy in zip(sections, composite):
            section.energy = float(energy)

    @staticmethod
    def _label_section(index: int, total: int, energy: float) -> str:
        """Heuristic labeling based on position and energy."""
        if index == 0:
            return "intro"
        if index == total - 1:
            return "outro"
        if energy > 0.65:
            return "chorus"
        if energy < 0.35:
            return "bridge"
        return "verse"
