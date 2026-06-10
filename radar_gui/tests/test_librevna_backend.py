"""Integration tests for LibreVNA SCPI backend using the mock server."""
import socket
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from radar_gui.librevna_backend import (
    LibreVnaScpiBackend,
    parse_scpi_trace_data,
    is_port_open,
    find_librevna_gui,
    is_librevna_usb_connected,
)
from radar_gui.models import SweepConfig


def _find_free_port():
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestParseScpiTraceData(unittest.TestCase):
    def test_valid_payload(self):
        payload = "1e9,0.5,0.3,2e9,0.1,-0.2,3e9,0.0,0.0"
        freq, s = parse_scpi_trace_data(payload)
        self.assertEqual(len(freq), 3)
        self.assertEqual(len(s), 3)
        self.assertAlmostEqual(freq[0], 1e9)
        self.assertAlmostEqual(s[0].real, 0.5)
        self.assertAlmostEqual(s[0].imag, 0.3)

    def test_scientific_notation(self):
        payload = "1.000000e+09,5.000000e-01,3.000000e-01"
        freq, s = parse_scpi_trace_data(payload)
        self.assertEqual(len(freq), 1)
        self.assertAlmostEqual(freq[0], 1e9)

    def test_empty_raises(self):
        from radar_gui.device_backends import BackendError
        with self.assertRaises(BackendError):
            parse_scpi_trace_data("")


class TestEndpointParsing(unittest.TestCase):
    def test_host_and_port(self):
        host, port = LibreVnaScpiBackend._parse_endpoint("192.168.1.100:19542")
        self.assertEqual(host, "192.168.1.100")
        self.assertEqual(port, 19542)

    def test_host_only(self):
        host, port = LibreVnaScpiBackend._parse_endpoint("myhost")
        self.assertEqual(host, "myhost")
        self.assertEqual(port, 19542)

    def test_localhost_default(self):
        host, port = LibreVnaScpiBackend._parse_endpoint("localhost:19542")
        self.assertEqual(host, "localhost")
        self.assertEqual(port, 19542)

    def test_empty_string(self):
        host, port = LibreVnaScpiBackend._parse_endpoint("")
        self.assertEqual(host, "localhost")
        self.assertEqual(port, 19542)


class TestIsPortOpen(unittest.TestCase):
    def test_closed_port(self):
        port = _find_free_port()
        self.assertFalse(is_port_open("127.0.0.1", port, timeout=0.1))


class TestLibreVnaBackendWithMockServer(unittest.TestCase):
    """Integration test using the existing mock_server from vna_gui."""

    @classmethod
    def setUpClass(cls):
        """Start the mock SCPI server in a background thread."""
        cls.port = _find_free_port()
        try:
            from vna_gui.vna_tester.mock_server import MockState, MockHandler, ThreadingTCPServer
            cls.state = MockState()
            handler = type("Bound", (MockHandler,), {"state": cls.state})
            cls.server = ThreadingTCPServer(("127.0.0.1", cls.port), handler)
            cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
            cls.server_thread.start()
            # Wait for server to be ready
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if is_port_open("127.0.0.1", cls.port, timeout=0.2):
                    break
                time.sleep(0.05)
            cls.mock_available = True
        except ImportError:
            cls.mock_available = False

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.shutdown()

    def setUp(self):
        if not self.mock_available:
            self.skipTest("vna_gui.vna_tester.mock_server not available")

    def test_connect_and_read(self):
        backend = LibreVnaScpiBackend(timeout=3.0)
        backend.connect(f"127.0.0.1:{self.port}")
        try:
            self.assertIn("LibreVNA", backend.device_info())

            # Configure a sweep
            cfg = SweepConfig(
                start_hz=1e9, stop_hz=2e9, points=51,
                poll_delay_s=0.01,
                backend_options={"ifbw_hz": 10000.0, "power_dbm": -10.0},
            )
            backend.configure_sweep(cfg)

            # Read a sweep
            frame = backend.read_sweep()
            self.assertEqual(frame.s21.size, 51)
            self.assertEqual(frame.freq_hz.size, 51)
            self.assertIsNotNone(frame.s11)
            if frame.s11 is not None:
                self.assertEqual(frame.s11.size, 51)
            self.assertAlmostEqual(frame.freq_hz[0], 1e9, delta=1e6)
            self.assertAlmostEqual(frame.freq_hz[-1], 2e9, delta=1e6)
            self.assertGreater(frame.timestamp, 0)
        finally:
            backend.disconnect()

    def test_device_info_format(self):
        backend = LibreVnaScpiBackend(timeout=3.0)
        backend.connect(f"127.0.0.1:{self.port}")
        try:
            info = backend.device_info()
            self.assertIn("LibreVNA", info)
            self.assertIn(str(self.port), info)
        finally:
            backend.disconnect()

    def test_disconnect_is_safe(self):
        backend = LibreVnaScpiBackend()
        # Disconnect without connect should not raise
        backend.disconnect()

    def test_safe_release_without_connect(self):
        backend = LibreVnaScpiBackend()
        # safe_release without connection should not raise
        backend.safe_release()


class TestFindLibreVnaGui(unittest.TestCase):
    def test_returns_path_or_none(self):
        """find_librevna_gui should return a Path or None, never raise."""
        result = find_librevna_gui()
        # On the dev machine with LibreVNA installed, this may return a path.
        # On CI it'll be None. Either is fine.
        if result is not None:
            self.assertTrue(result.exists())


class TestLibreVnaUsbConnection(unittest.TestCase):
    def test_is_connected_returns_bool(self):
        res = is_librevna_usb_connected()
        self.assertIsInstance(res, bool)


if __name__ == "__main__":
    unittest.main()
