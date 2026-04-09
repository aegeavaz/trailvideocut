import numpy as np

from trailvideocut.audio.energy_curve import (
    compute_smoothed_energy,
    detect_energy_transitions,
)


class TestComputeSmoothedEnergy:
    def test_output_shape_matches_input(self):
        env = np.random.rand(500)
        energy, times = compute_smoothed_energy(env, sr=22050)
        assert len(energy) == len(env)
        assert len(times) == len(env)

    def test_output_normalized_zero_one(self):
        env = np.random.rand(500) * 100
        energy, _ = compute_smoothed_energy(env)
        assert energy.min() >= 0.0 - 1e-9
        assert energy.max() <= 1.0 + 1e-9

    def test_constant_input_produces_flat_curve(self):
        env = np.ones(500) * 0.5
        energy, _ = compute_smoothed_energy(env)
        # All zeros since constant input normalizes to 0
        assert np.std(energy) < 0.01

    def test_step_function_smoothed(self):
        """A step function should produce a smooth transition, not a hard edge."""
        env = np.concatenate([np.zeros(250), np.ones(250)])
        energy, _ = compute_smoothed_energy(env, smooth_window_sec=1.0)
        deriv = np.abs(np.diff(energy))
        # No single-frame jump should be more than 0.15 (smoothed)
        assert deriv.max() < 0.15

    def test_empty_input(self):
        energy, times = compute_smoothed_energy(np.array([]))
        assert len(energy) == 0
        assert len(times) == 0

    def test_times_are_monotonically_increasing(self):
        env = np.random.rand(500)
        _, times = compute_smoothed_energy(env, sr=22050)
        assert all(times[i] < times[i + 1] for i in range(len(times) - 1))


class TestDetectEnergyTransitions:
    def test_detects_large_step_up(self):
        """A sharp energy step should be detected."""
        env = np.concatenate([np.zeros(250), np.ones(250)])
        energy, times = compute_smoothed_energy(env, sr=22050)
        transitions = detect_energy_transitions(energy, times, min_magnitude=0.3)
        assert len(transitions) >= 1
        # Transition should be near the midpoint
        mid_time = times[250]
        assert any(abs(t.timestamp - mid_time) < 2.0 for t in transitions)

    def test_no_transition_on_flat(self):
        env = np.ones(500) * 0.5
        energy, times = compute_smoothed_energy(env)
        transitions = detect_energy_transitions(energy, times, min_magnitude=0.3)
        assert len(transitions) == 0

    def test_direction_up_and_down(self):
        """Up-then-down pattern should detect both directions."""
        env = np.concatenate([np.zeros(200), np.ones(200), np.zeros(200)])
        energy, times = compute_smoothed_energy(env, sr=22050)
        transitions = detect_energy_transitions(energy, times, min_magnitude=0.3)
        directions = {t.direction for t in transitions}
        assert "up" in directions
        assert "down" in directions

    def test_min_gap_prevents_clustering(self):
        """Transitions closer than min_gap_sec should be deduplicated."""
        # Rapid oscillation
        env = np.zeros(1000)
        for i in range(0, 1000, 50):
            env[i : i + 25] = 1.0
        energy, times = compute_smoothed_energy(env, sr=22050)
        transitions = detect_energy_transitions(energy, times, min_gap_sec=2.0)
        for i in range(1, len(transitions)):
            gap = transitions[i].timestamp - transitions[i - 1].timestamp
            assert gap >= 2.0 - 0.01

    def test_min_magnitude_filters_small_changes(self):
        """Small energy swings below threshold should not be detected."""
        # Manually craft a normalized curve with a small ~15% bump
        times = np.linspace(0, 10, 500)
        energy = np.full(500, 0.4)
        energy[200:300] = 0.55  # only 0.15 swing
        # Smooth to avoid hard edges triggering peaks
        from scipy.ndimage import gaussian_filter1d
        energy = gaussian_filter1d(energy, sigma=5)
        transitions = detect_energy_transitions(energy, times, min_magnitude=0.3)
        assert len(transitions) == 0

    def test_magnitude_reflects_energy_swing(self):
        """Detected transition magnitude should reflect actual energy change."""
        env = np.concatenate([np.zeros(250), np.ones(250)])
        energy, times = compute_smoothed_energy(env, sr=22050)
        transitions = detect_energy_transitions(energy, times, min_magnitude=0.2)
        assert len(transitions) >= 1
        # The magnitude should be substantial (close to 1.0 for a full step)
        assert transitions[0].magnitude >= 0.5

    def test_short_input_returns_empty(self):
        energy = np.array([0.5, 0.5])
        times = np.array([0.0, 0.5])
        transitions = detect_energy_transitions(energy, times)
        assert transitions == []

    def test_returns_sorted_by_timestamp(self):
        """Multiple transitions should be sorted chronologically."""
        # Two distinct transitions far apart
        env = np.concatenate([
            np.zeros(200), np.ones(200),
            np.zeros(200), np.ones(200),
        ])
        energy, times = compute_smoothed_energy(env, sr=22050)
        transitions = detect_energy_transitions(energy, times, min_magnitude=0.3, min_gap_sec=1.0)
        for i in range(1, len(transitions)):
            assert transitions[i].timestamp >= transitions[i - 1].timestamp
