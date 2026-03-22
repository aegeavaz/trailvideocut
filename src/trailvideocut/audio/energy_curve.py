"""Fine-grained energy curve analysis and transition detection.

Computes a smoothed energy curve from the onset envelope at ~1s resolution
and detects significant energy transitions (build-ups, drops) that should
force cut points even within a single music section.
"""

from dataclasses import dataclass

import librosa
import numpy as np
from scipy.ndimage import gaussian_filter1d


@dataclass
class EnergyTransition:
    """A detected significant energy transition."""

    timestamp: float
    magnitude: float  # absolute change in normalized energy (0-1 scale)
    direction: str  # "up" or "down"


def compute_smoothed_energy(
    onset_envelope: np.ndarray,
    sr: int = 22050,
    hop_length: int = 512,
    smooth_window_sec: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute a smoothed energy curve from the onset envelope.

    Parameters
    ----------
    onset_envelope : np.ndarray
        Frame-level onset strength (from librosa.onset.onset_strength).
    sr : int
        Sample rate used when computing the onset envelope.
    hop_length : int
        Hop length used when computing the onset envelope.
    smooth_window_sec : float
        Gaussian smoothing window width in seconds.

    Returns
    -------
    energy : np.ndarray
        Smoothed, normalized energy curve (values in [0, 1]).
    times : np.ndarray
        Corresponding time in seconds for each energy sample.
    """
    if len(onset_envelope) == 0:
        return np.array([]), np.array([])

    window_frames = max(1, int(smooth_window_sec * sr / hop_length))
    sigma = window_frames / 4.0

    smoothed = gaussian_filter1d(onset_envelope.astype(float), sigma=sigma)

    # Normalize to [0, 1]
    mn, mx = smoothed.min(), smoothed.max()
    if mx - mn > 0:
        energy = (smoothed - mn) / (mx - mn)
    else:
        energy = np.zeros_like(smoothed)

    times = librosa.frames_to_time(
        np.arange(len(energy)), sr=sr, hop_length=hop_length
    )

    return energy, times


def detect_energy_transitions(
    energy: np.ndarray,
    times: np.ndarray,
    min_magnitude: float = 0.3,
    min_gap_sec: float = 2.0,
) -> list[EnergyTransition]:
    """Detect significant energy transitions in a smoothed energy curve.

    Parameters
    ----------
    energy : np.ndarray
        Smoothed energy curve from compute_smoothed_energy().
    times : np.ndarray
        Time axis corresponding to energy.
    min_magnitude : float
        Minimum absolute energy swing (on 0-1 scale) to qualify as a
        transition. Default 0.3 means a 30% energy shift.
    min_gap_sec : float
        Minimum time between detected transitions to prevent clustering.

    Returns
    -------
    List of EnergyTransition objects sorted by timestamp.
    """
    if len(energy) < 3 or len(times) < 3:
        return []

    # Compute derivative (energy change per second)
    dt = np.diff(times)
    dt[dt == 0] = 1e-9  # avoid division by zero
    deriv = np.diff(energy) / dt
    abs_deriv = np.abs(deriv)

    # Find local peaks in absolute derivative
    peaks: list[int] = []
    for i in range(1, len(abs_deriv) - 1):
        if abs_deriv[i] > abs_deriv[i - 1] and abs_deriv[i] > abs_deriv[i + 1]:
            peaks.append(i)

    if not peaks:
        return []

    # Measure actual energy swing in a window around each peak
    candidates: list[tuple[float, float, str]] = []  # (timestamp, magnitude, direction)
    frame_rate = 1.0 / (times[1] - times[0]) if len(times) > 1 and times[1] > times[0] else 1.0
    window_frames = max(1, int(1.0 * frame_rate))  # ~1s window each side

    for peak_idx in peaks:
        lo = max(0, peak_idx - window_frames)
        hi = min(len(energy), peak_idx + window_frames + 1)
        window_energy = energy[lo:hi]

        local_min = float(window_energy.min())
        local_max = float(window_energy.max())
        magnitude = local_max - local_min

        if magnitude < min_magnitude:
            continue

        # Determine direction: energy before vs after the peak
        before = float(energy[lo])
        after = float(energy[min(hi - 1, len(energy) - 1)])
        direction = "up" if after > before else "down"

        # Use the derivative peak time (offset by 0.5 since deriv is between frames)
        timestamp = float((times[peak_idx] + times[min(peak_idx + 1, len(times) - 1)]) / 2)
        candidates.append((timestamp, magnitude, direction))

    if not candidates:
        return []

    # Sort by magnitude descending for dedup (keep strongest)
    candidates.sort(key=lambda c: c[1], reverse=True)

    # Deduplicate: enforce min_gap_sec between transitions
    kept: list[EnergyTransition] = []
    for ts, mag, direction in candidates:
        if all(abs(ts - k.timestamp) >= min_gap_sec for k in kept):
            kept.append(EnergyTransition(timestamp=ts, magnitude=mag, direction=direction))

    # Sort by timestamp
    kept.sort(key=lambda t: t.timestamp)
    return kept
