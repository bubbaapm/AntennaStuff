"""Tests for radar_gui.device_backends."""
import unittest
import struct
import numpy as np
from radar_gui.device_backends import (
    parse_litevna_samples,
    parse_complex_lines,
    parse_frequency_lines,
    make_backend,
    BackendError,
    SAMPLE_SIZE,
    SAMPLE_STRUCT,
)


class TestParseLiteVnaSamples(unittest.TestCase):
    def _make_sample_bytes(self, n_points):
        """Build synthetic sample data matching the LiteVNA 32-byte format."""
        data = bytearray()
        for idx in range(n_points):
            # fwd = (1000, 0), refl = (100, 50), thru = (200, -100)
            sample = SAMPLE_STRUCT.pack(
                1000, 0,      # fwd_re, fwd_im
                100, 50,      # refl_re, refl_im
                200, -100,    # thru_re, thru_im
                idx,          # freq_index
                b'\x00' * 5,  # padding
                0,            # flags
            )
            data.extend(sample)
        return bytes(data)

    def test_valid_parsing(self):
        n = 10
        data = self._make_sample_bytes(n)
        s11, s21 = parse_litevna_samples(data, n)
        self.assertEqual(len(s11), n)
        self.assertEqual(len(s21), n)
        # Check S11 = refl / fwd = (100+50j) / (1000+0j) = 0.1+0.05j
        self.assertAlmostEqual(s11[0].real, 0.1)
        self.assertAlmostEqual(s11[0].imag, 0.05)
        # Check S21 = thru / fwd = (200-100j) / (1000+0j) = 0.2-0.1j
        self.assertAlmostEqual(s21[0].real, 0.2)
        self.assertAlmostEqual(s21[0].imag, -0.1)

    def test_wrong_data_length_raises(self):
        with self.assertRaises(BackendError):
            parse_litevna_samples(b'\x00' * 10, 5)  # wrong size


class TestParseComplexLines(unittest.TestCase):
    def test_valid_lines(self):
        lines = ["0.5 -0.3", "0.1 0.2", "0.0 0.0"]
        result = parse_complex_lines(lines)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0], 0.5 - 0.3j)

    def test_skips_short_lines(self):
        lines = ["0.5 -0.3", "bad", "0.1 0.2"]
        result = parse_complex_lines(lines)
        self.assertEqual(len(result), 2)

    def test_empty_input(self):
        result = parse_complex_lines([])
        self.assertEqual(len(result), 0)


class TestParseFrequencyLines(unittest.TestCase):
    def test_valid_lines(self):
        lines = ["1000000000", "2000000000", "3000000000"]
        result = parse_frequency_lines(lines)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0], 1e9)

    def test_skips_empty_lines(self):
        lines = ["1000000000", "", "2000000000"]
        result = parse_frequency_lines(lines)
        self.assertEqual(len(result), 2)


class TestMakeBackend(unittest.TestCase):
    def test_default_is_litevna(self):
        from radar_gui.device_backends import LiteVnaBackend
        backend = make_backend("LiteVNA / NanoVNA V2")
        self.assertIsInstance(backend, LiteVnaBackend)

    def test_shell_backend(self):
        from radar_gui.device_backends import NanoVnaShellBackend
        backend = make_backend("NanoVNA Shell")
        self.assertIsInstance(backend, NanoVnaShellBackend)

    def test_nanovna_key(self):
        from radar_gui.device_backends import NanoVnaShellBackend
        backend = make_backend("nanovna")
        self.assertIsInstance(backend, NanoVnaShellBackend)

    def test_librevna_key(self):
        from radar_gui.librevna_backend import LibreVnaScpiBackend
        backend = make_backend("LibreVNA (SCPI)")
        self.assertIsInstance(backend, LibreVnaScpiBackend)

    def test_scpi_key(self):
        from radar_gui.librevna_backend import LibreVnaScpiBackend
        backend = make_backend("scpi")
        self.assertIsInstance(backend, LibreVnaScpiBackend)

    def test_libre_key(self):
        from radar_gui.librevna_backend import LibreVnaScpiBackend
        backend = make_backend("libre")
        self.assertIsInstance(backend, LibreVnaScpiBackend)


if __name__ == "__main__":
    unittest.main()
