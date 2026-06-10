"""Tests for radar_gui.models."""
import unittest
from radar_gui.models import SweepConfig, RadarConfig, Peak, BackgroundProfile, CaptureSession
import numpy as np


class TestSweepConfig(unittest.TestCase):
    def test_default_values(self):
        cfg = SweepConfig()
        self.assertEqual(cfg.start_hz, 5.0e9)
        self.assertEqual(cfg.stop_hz, 5.4e9)
        self.assertEqual(cfg.points, 501)

    def test_bandwidth_hz(self):
        cfg = SweepConfig(start_hz=1e9, stop_hz=2e9)
        self.assertAlmostEqual(cfg.bandwidth_hz, 1e9)

    def test_frequency_axis(self):
        cfg = SweepConfig(start_hz=1e9, stop_hz=2e9, points=11)
        axis = cfg.frequency_axis()
        self.assertEqual(len(axis), 11)
        self.assertAlmostEqual(axis[0], 1e9)
        self.assertAlmostEqual(axis[-1], 2e9)

    def test_round_trip_dict(self):
        cfg = SweepConfig(start_hz=2e9, stop_hz=3e9, points=101, poll_delay_s=0.05)
        d = cfg.to_dict()
        cfg2 = SweepConfig.from_dict(d)
        self.assertEqual(cfg, cfg2)

    def test_from_dict_with_float_points(self):
        """Points might arrive as float from JSON."""
        d = {"start_hz": 1e9, "stop_hz": 2e9, "points": 101.0, "mode": "s21",
             "power": "max", "poll_delay_s": 0.02, "backend_options": {}}
        cfg = SweepConfig.from_dict(d)
        self.assertEqual(cfg.points, 101)
        self.assertIsInstance(cfg.points, int)

    def test_backend_options_default_empty(self):
        cfg = SweepConfig()
        self.assertEqual(cfg.backend_options, {})

    def test_backend_options_round_trip(self):
        cfg = SweepConfig(backend_options={"ifbw_hz": 5000, "power_dbm": -10.0})
        d = cfg.to_dict()
        cfg2 = SweepConfig.from_dict(d)
        self.assertEqual(cfg2.backend_options["ifbw_hz"], 5000)
        self.assertAlmostEqual(cfg2.backend_options["power_dbm"], -10.0)


class TestRadarConfig(unittest.TestCase):
    def test_round_trip_dict(self):
        cfg = RadarConfig(ema_alpha=0.5, window="hamming", range_max_m=20.0)
        d = cfg.to_dict()
        cfg2 = RadarConfig.from_dict(d)
        self.assertEqual(cfg, cfg2)


class TestPeak(unittest.TestCase):
    def test_to_dict(self):
        p = Peak(distance_m=3.5, amplitude=0.01, index=42, prominence=0.005)
        d = p.to_dict()
        self.assertAlmostEqual(d["distance_m"], 3.5)
        self.assertEqual(d["index"], 42)


class TestBackgroundProfile(unittest.TestCase):
    def test_metadata(self):
        cfg = SweepConfig(start_hz=1e9, stop_hz=2e9, points=51)
        bg = BackgroundProfile(
            name="test_bg",
            sweep_config=cfg,
            complex_s21_avg=np.zeros(51, dtype=complex),
            created_at=1000.0,
            notes="test",
            device_id="dev1",
        )
        meta = bg.metadata()
        self.assertEqual(meta["name"], "test_bg")
        self.assertEqual(meta["device_id"], "dev1")
        self.assertEqual(meta["sweep_config"]["points"], 51)


class TestCaptureSession(unittest.TestCase):
    def test_frame_count(self):
        s21 = np.zeros((10, 51), dtype=complex)
        session = CaptureSession(
            name="test",
            sweep_config=SweepConfig(),
            radar_config=RadarConfig(),
            timestamps=np.arange(10, dtype=float),
            freq_hz=np.linspace(1e9, 2e9, 51),
            s21_frames=s21,
        )
        self.assertEqual(session.frame_count(), 10)


if __name__ == "__main__":
    unittest.main()
