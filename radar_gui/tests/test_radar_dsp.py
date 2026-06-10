"""Tests for radar_gui.radar_dsp."""
import unittest
import numpy as np
from radar_gui.radar_dsp import (
    distance_axis,
    make_window,
    apply_complex_ema,
    detect_peaks,
    normalize_for_waterfall,
    process_s21,
)
from radar_gui.models import SweepConfig, RadarConfig, SPEED_OF_LIGHT_M_S


class TestDistanceAxis(unittest.TestCase):
    def test_basic_shape(self):
        cfg = SweepConfig(start_hz=1e9, stop_hz=2e9, points=101)
        axis = distance_axis(cfg)
        self.assertEqual(len(axis), 101)

    def test_zero_padded_shape(self):
        cfg = SweepConfig(start_hz=1e9, stop_hz=2e9, points=101)
        axis = distance_axis(cfg, bins=2048)
        self.assertEqual(len(axis), 2048)

    def test_starts_at_zero(self):
        cfg = SweepConfig(start_hz=1e9, stop_hz=2e9, points=101)
        axis = distance_axis(cfg)
        self.assertAlmostEqual(axis[0], 0.0)

    def test_spacing_proportional_to_bandwidth(self):
        cfg_narrow = SweepConfig(start_hz=1e9, stop_hz=1.5e9, points=101)
        cfg_wide = SweepConfig(start_hz=1e9, stop_hz=2e9, points=101)
        axis_narrow = distance_axis(cfg_narrow)
        axis_wide = distance_axis(cfg_wide)
        # Wider bandwidth → finer range spacing
        self.assertGreater(axis_narrow[1], axis_wide[1])


class TestMakeWindow(unittest.TestCase):
    def test_hann(self):
        w = make_window("hann", 64)
        self.assertEqual(len(w), 64)
        self.assertAlmostEqual(w[0], 0.0, places=5)

    def test_hamming(self):
        w = make_window("hamming", 64)
        self.assertEqual(len(w), 64)
        self.assertGreater(w[0], 0.0)  # Hamming doesn't go to zero

    def test_rectangular(self):
        w = make_window("rect", 64)
        np.testing.assert_array_equal(w, np.ones(64))

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            make_window("invalid_window", 64)


class TestComplexEma(unittest.TestCase):
    def test_first_frame_is_copy(self):
        current = np.array([1 + 2j, 3 + 4j])
        result = apply_complex_ema(current, None, 0.5)
        np.testing.assert_array_equal(result, current)

    def test_alpha_one_is_current(self):
        prev = np.array([10 + 0j, 20 + 0j])
        curr = np.array([1 + 0j, 2 + 0j])
        result = apply_complex_ema(curr, prev, 1.0)
        np.testing.assert_array_almost_equal(result, curr)

    def test_alpha_zero_is_previous(self):
        prev = np.array([10 + 0j, 20 + 0j])
        curr = np.array([1 + 0j, 2 + 0j])
        result = apply_complex_ema(curr, prev, 0.0)
        np.testing.assert_array_almost_equal(result, prev)

    def test_shape_mismatch_returns_current(self):
        prev = np.array([1 + 0j, 2 + 0j, 3 + 0j])
        curr = np.array([1 + 0j, 2 + 0j])
        result = apply_complex_ema(curr, prev, 0.5)
        np.testing.assert_array_equal(result, curr)


class TestDetectPeaks(unittest.TestCase):
    def test_single_peak(self):
        distance = np.linspace(0, 10, 100)
        mag = np.exp(-((distance - 5.0) ** 2) / 0.1)  # Gaussian peak at 5 m
        cfg = RadarConfig(peak_threshold=0.0, peak_prominence=0.0, max_peaks=3)
        peaks = detect_peaks(distance, mag, cfg)
        self.assertGreater(len(peaks), 0)
        self.assertAlmostEqual(peaks[0].distance_m, 5.0, places=0)

    def test_empty_magnitude(self):
        peaks = detect_peaks(np.array([]), np.array([]), RadarConfig())
        self.assertEqual(peaks, [])


class TestNormalizeForWaterfall(unittest.TestCase):
    def test_output_range(self):
        mag = np.array([0.0, 0.5, 1.0, 2.0, 10.0])
        normed = normalize_for_waterfall(mag)
        self.assertTrue(np.all(normed >= 0.0))
        self.assertTrue(np.all(normed <= 1.0))

    def test_empty_input(self):
        result = normalize_for_waterfall(np.array([]))
        self.assertEqual(result.size, 0)


class TestProcessS21(unittest.TestCase):
    def test_basic_processing(self):
        """Process a synthetic sweep and check output shape."""
        n_pts = 101
        sweep_cfg = SweepConfig(start_hz=1e9, stop_hz=2e9, points=n_pts)
        radar_cfg = RadarConfig(range_min_m=0.0, range_max_m=50.0, range_fft_points=256)
        s21 = np.random.randn(n_pts) + 1j * np.random.randn(n_pts)
        frame, ema = process_s21(s21, sweep_cfg, radar_cfg)
        self.assertGreater(frame.distance_m.size, 0)
        self.assertEqual(frame.distance_m.size, frame.magnitude.size)
        self.assertEqual(ema.size, n_pts)

    def test_background_subtraction(self):
        n_pts = 51
        sweep_cfg = SweepConfig(start_hz=1e9, stop_hz=2e9, points=n_pts)
        radar_cfg = RadarConfig()
        background = np.ones(n_pts, dtype=complex) * (0.5 + 0.5j)
        s21 = np.ones(n_pts, dtype=complex) * (0.5 + 0.5j)
        # With identical background + signal, subtracted should be ~zero
        frame, _ = process_s21(s21, sweep_cfg, radar_cfg, background=background)
        self.assertAlmostEqual(np.max(frame.magnitude), 0.0, places=10)

    def test_shape_mismatch_raises(self):
        sweep_cfg = SweepConfig(start_hz=1e9, stop_hz=2e9, points=101)
        radar_cfg = RadarConfig()
        s21 = np.zeros(50, dtype=complex)  # wrong size
        with self.assertRaises(ValueError):
            process_s21(s21, sweep_cfg, radar_cfg)


if __name__ == "__main__":
    unittest.main()
