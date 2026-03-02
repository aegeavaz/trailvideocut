import numpy as np
import librosa

from smartcut.audio.models import MusicSection


class MusicalStructureAnalyzer:
    """Detect musical structure (intro/verse/chorus/bridge/outro) via spectral segmentation."""

    def analyze(self, audio_path: str, sr: int = 22050) -> list[MusicSection]:
        """Segment the audio into structural sections."""
        y, sr = librosa.load(audio_path, sr=sr)
        duration = librosa.get_duration(y=y, sr=sr)

        # Compute chroma features for segmentation
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)

        # Determine number of sections (roughly one per 30 seconds)
        n_sections = min(8, max(3, int(duration / 30)))

        # Agglomerative clustering on chroma to find boundaries
        boundary_frames = librosa.segment.agglomerative(chroma, n_sections)
        boundary_times = librosa.frames_to_time(boundary_frames, sr=sr)

        # Compute RMS energy for labeling
        rms = librosa.feature.rms(y=y)[0]
        rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)

        # Build sections
        all_boundaries = [0.0] + sorted(boundary_times.tolist()) + [duration]
        sections = []
        for i in range(len(all_boundaries) - 1):
            start, end = all_boundaries[i], all_boundaries[i + 1]
            mask = (rms_times >= start) & (rms_times < end)
            energy = float(np.mean(rms[mask])) if mask.any() else 0.0
            label = self._label_section(i, len(all_boundaries) - 1, energy)
            sections.append(MusicSection(label=label, start_time=start, end_time=end, energy=energy))

        # Normalize energy across sections
        max_energy = max((s.energy for s in sections), default=1.0)
        if max_energy > 0:
            for s in sections:
                s.energy = s.energy / max_energy

        return sections

    def _label_section(self, index: int, total: int, energy: float) -> str:
        """Heuristic labeling based on position and energy."""
        if index == 0:
            return "intro"
        if index == total - 1:
            return "outro"
        if energy > 0.7:
            return "chorus"
        if energy < 0.3:
            return "bridge"
        return "verse"
