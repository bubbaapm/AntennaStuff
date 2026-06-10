"""
LibreVNA SCPI-over-TCP backend for the radar GUI.

Connects to the LibreVNA-GUI's SCPI server (default localhost:19542),
configures sweep parameters, and reads S11/S21 trace data. Includes
auto-launch logic for LibreVNA-GUI and calibration file loading.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .device_backends import BackendError, BackendTimeout, DeviceBackend
from .models import SweepConfig, SweepFrame
from .scpi_client import ScpiClient, ScpiError


# --------------------------------------------------------------------------
# Trace data parser (locally owned, matches LibreVNA SCPI response format)
# --------------------------------------------------------------------------

_NUMERIC = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def parse_scpi_trace_data(payload: str) -> Tuple[np.ndarray, np.ndarray]:
    """Parse ':VNA:TRAC:DATA? Sxx' response into (freq_hz, complex_s).

    LibreVNA-GUI returns comma-separated triplets: freq,re,im,freq,re,im,...
    """
    nums = [float(m.group(0)) for m in _NUMERIC.finditer(payload)]
    if len(nums) % 3 != 0:
        nums = nums[: (len(nums) // 3) * 3]
    if not nums:
        raise BackendError("Empty trace data from LibreVNA")
    arr = np.asarray(nums, dtype=float).reshape(-1, 3)
    freq = arr[:, 0]
    s = arr[:, 1] + 1j * arr[:, 2]
    return freq, s


# --------------------------------------------------------------------------
# LibreVNA-GUI auto-discovery and launcher
# --------------------------------------------------------------------------

_LIBREVNA_EXE_NAMES = ("LibreVNA-GUI.exe", "LibreVNA-GUI")


def _is_librevna(path: Path) -> bool:
    return path.is_file() and path.name in _LIBREVNA_EXE_NAMES


def is_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    """Check if a TCP port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_librevna_gui() -> Optional[Path]:
    """Search common locations for LibreVNA-GUI executable.

    Priority:
    1. LibreVNA/release/ relative to the project root (the primary location)
    2. Sibling directories up the tree
    3. Common Windows install paths
    4. System PATH
    """
    # Start from the radar_gui package's parent (the repo root)
    app_dir = Path(__file__).resolve().parent
    project_root = app_dir.parent

    # 1. Primary location: LibreVNA/release/ at repo root
    primary = project_root / "LibreVNA" / "release" / "LibreVNA-GUI.exe"
    if _is_librevna(primary):
        return primary

    # 2. Walk up from project root checking sibling locations
    walk = project_root
    for _ in range(5):
        for sub in (
            "LibreVNA/release",
            "LibreVNA",
            "librevna/release",
            "librevna",
        ):
            for name in _LIBREVNA_EXE_NAMES:
                cand = walk / sub / name
                if _is_librevna(cand):
                    return cand
        if walk.parent == walk:
            break
        walk = walk.parent

    # 3. Common Windows install paths
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            for sub in ("LibreVNA", "LibreVNA-GUI"):
                for name in _LIBREVNA_EXE_NAMES:
                    for subdir in ("", "release"):
                        cand = Path(root) / sub / subdir / name if subdir else Path(root) / sub / name
                        if _is_librevna(cand):
                            return cand

    # 4. System PATH
    import shutil
    on_path = shutil.which("LibreVNA-GUI") or shutil.which("LibreVNA-GUI.exe")
    if on_path:
        p = Path(on_path)
        if _is_librevna(p):
            return p

    return None


def is_librevna_usb_connected() -> bool:
    """Check if LibreVNA hardware is plugged into the USB port on Windows."""
    import sys
    if sys.platform != "win32":
        return False
    try:
        import winreg
        for service in ("WinUSB", "libusbk", "libusb0", "libusb"):
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    f"SYSTEM\\CurrentControlSet\\Services\\{service}\\Enum"
                )
                try:
                    count_val, _ = winreg.QueryValueEx(key, "Count")
                    count = int(count_val)
                except OSError:
                    count = 100
                for i in range(count):
                    try:
                        _, val, _ = winreg.EnumValue(key, i)
                        if isinstance(val, str) and "VID_1209&PID_4121" in val.upper():
                            return True
                    except OSError:
                        break
            except OSError:
                continue
    except Exception:
        pass
    return False




import atexit

_ACTIVE_LAUNCHERS: list[LibreVnaLauncher] = []


def _cleanup_launchers() -> None:
    for launcher in list(_ACTIVE_LAUNCHERS):
        try:
            launcher.stop()
        except Exception:
            pass


atexit.register(_cleanup_launchers)


class LibreVnaLauncher:
    """Wraps a LibreVNA-GUI subprocess. Idempotent — won't double-spawn."""

    def __init__(self, exe_path: Optional[Path] = None,
                 host: str = "localhost", port: int = 19542):
        self.exe_path = exe_path
        self.host = host
        self.port = port
        self._proc: Optional[subprocess.Popen] = None
        self._owned = False  # True if WE started it; we'll clean it up.
        _ACTIVE_LAUNCHERS.append(self)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ensure_running(self, wait_seconds: float = 8.0,
                       headless: bool = True) -> bool:
        """Make sure the SCPI port is reachable.

        If something is already listening, do nothing. Otherwise spawn
        LibreVNA-GUI ourselves. Returns True if the port is reachable.
        """
        print(f"[DEBUG] LibreVnaLauncher.ensure_running host={self.host} port={self.port}", flush=True)
        if is_port_open(self.host, self.port):
            print("[DEBUG] LibreVnaLauncher.ensure_running: port is already open", flush=True)
            return True

        if self.exe_path is None:
            self.exe_path = find_librevna_gui()
            print(f"[DEBUG] LibreVnaLauncher.ensure_running: find_librevna_gui returned {self.exe_path}", flush=True)
        if self.exe_path is None or not self.exe_path.exists():
            print("[DEBUG] LibreVnaLauncher.ensure_running: exe path not found or doesn't exist", flush=True)
            return False

        args: list[str] = [str(self.exe_path)]
        if headless:
            args.append("--no-gui")
        print(f"[DEBUG] LibreVnaLauncher.ensure_running: spawning args={args}", flush=True)

        # Windows subprocess flags
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )

        # Clean Qt env vars to avoid conflicts with our Qt
        env = os.environ.copy()
        for k in (
            "QT_QPA_PLATFORM", "QT_QPA_PLATFORM_PLUGIN_PATH",
            "QT_PLUGIN_PATH", "QT_AUTO_SCREEN_SCALE_FACTOR",
            "QT_SCALE_FACTOR", "QT_DEBUG_PLUGINS",
        ):
            env.pop(k, None)
        if headless and sys.platform.startswith("linux") and not env.get("DISPLAY"):
            env["QT_QPA_PLATFORM"] = "offscreen"

        try:
            self._proc = subprocess.Popen(
                args,
                cwd=str(self.exe_path.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
                env=env,
            )
            self._owned = True
            print(f"[DEBUG] LibreVnaLauncher.ensure_running: spawned process pid={self._proc.pid}", flush=True)
        except OSError as e:
            self._proc = None
            print(f"[DEBUG] LibreVnaLauncher.ensure_running: failed to spawn: {e}", flush=True)
            return False

        # Poll for the SCPI port to come up
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if is_port_open(self.host, self.port):
                print(f"[DEBUG] LibreVnaLauncher.ensure_running: port became open", flush=True)
                return True
            poll_res = self._proc.poll()
            if poll_res is not None:
                print(f"[DEBUG] LibreVnaLauncher.ensure_running: subprocess exited early with code {poll_res}", flush=True)
                return False
            time.sleep(0.25)
        res = is_port_open(self.host, self.port)
        print(f"[DEBUG] LibreVnaLauncher.ensure_running: finished wait, port open={res}", flush=True)
        return res

    def stop(self) -> None:
        """Kill the subprocess only if we started it."""
        if self in _ACTIVE_LAUNCHERS:
            try:
                _ACTIVE_LAUNCHERS.remove(self)
            except ValueError:
                pass
        if self._proc is None or not self._owned:
            self._proc = None
            return
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        except OSError:
            pass
        self._proc = None


# --------------------------------------------------------------------------
# LibreVNA Device Backend
# --------------------------------------------------------------------------

class LibreVnaScpiBackend(DeviceBackend):
    """Backend for LibreVNA via LibreVNA-GUI's SCPI server."""

    name = "LibreVNA (SCPI)"

    def __init__(self, timeout: float = 5.0) -> None:
        super().__init__()
        self._timeout = timeout
        self._client: Optional[ScpiClient] = None
        self._host = "localhost"
        self._port_num = 19542
        self._device_serial = ""
        self._idn = ""
        self._launcher: Optional[LibreVnaLauncher] = None

    def connect(self, port: str) -> None:
        """Connect to LibreVNA-GUI SCPI server.

        Args:
            port: "host:port" string, e.g. "localhost:19542".
                  Plain "host" defaults to port 19542.
        """
        self.port = port
        host, port_num = self._parse_endpoint(port)
        self._host = host
        self._port_num = port_num
        self._client = ScpiClient(
            host=host, port=port_num, timeout=self._timeout
        )
        try:
            self._client.connect()
        except ScpiError as e:
            self._client = None
            raise BackendError(
                f"Cannot connect to LibreVNA SCPI at {host}:{port_num}: {e}"
            ) from e

        # Ensure VNA mode
        try:
            self._client.write(":DEV:MODE VNA")
        except ScpiError:
            pass

        # Read identity
        try:
            self._idn = self._client.query("*IDN?").strip()
        except ScpiError:
            self._idn = "LibreVNA"

        # Connect to the first available device if none connected
        try:
            serial = self._client.query(":DEV:CONN?").strip()
            if not serial or serial.upper() == "NOT CONNECTED":
                devices = self._client.query(":DEV:LIST?").strip()
                if devices:
                    first = devices.split(",")[0].strip()
                    if first:
                        self._client.write(f":DEV:CONN {first}")
                        serial = first
            self._device_serial = serial
        except ScpiError:
            self._device_serial = ""

        # Ensure S11 and S21 traces exist
        self._ensure_traces()

    def disconnect(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
        finally:
            self._client = None

    def safe_release(self) -> None:
        if self._client is None or not self._client.connected:
            return
        try:
            self._client.write(":VNA:ACQ:STOP")
        except ScpiError:
            pass

    def configure_sweep(self, config: SweepConfig) -> None:
        self._require_client()
        self._config = config
        c = self._client
        assert c is not None
        try:
            c.write(":VNA:ACQ:STOP")
            c.write(":VNA:SWEEP FREQUENCY")
            c.write(f":VNA:FREQ:START {config.start_hz:.6f}")
            c.write(f":VNA:FREQ:STOP {config.stop_hz:.6f}")
            c.write(f":VNA:ACQ:POINTS {int(config.points)}")

            # LibreVNA-specific: IFBW
            ifbw = float(config.backend_options.get("ifbw_hz", 10_000.0))
            c.write(f":VNA:ACQ:IFBW {ifbw:.3f}")

            # LibreVNA-specific: averaging
            avg = int(config.backend_options.get("averaging", 1))
            c.write(f":VNA:ACQ:AVG {max(1, avg)}")

            # LibreVNA-specific: power level
            power_dbm = config.backend_options.get("power_dbm")
            if power_dbm is not None:
                c.write(f":VNA:STIM:LVL {float(power_dbm):.2f}")

            c.write(":VNA:ACQ:RUN TRUE")
        except ScpiError as e:
            raise BackendError(f"LibreVNA sweep config failed: {e}") from e

    def read_sweep(self) -> SweepFrame:
        self._require_client()
        assert self._client is not None
        try:
            # Query S21 (always needed for radar)
            payload_s21 = self._client.query(":VNA:TRAC:DATA? S21")
            freq_hz, s21 = parse_scpi_trace_data(payload_s21)

            # Query S11 (optional but available on LibreVNA)
            s11: Optional[np.ndarray] = None
            try:
                payload_s11 = self._client.query(":VNA:TRAC:DATA? S11")
                _, s11 = parse_scpi_trace_data(payload_s11)
            except (ScpiError, BackendError):
                pass

            return SweepFrame(
                freq_hz=freq_hz,
                s11=s11,
                s21=s21,
                timestamp=time.time(),
                device_id=self.device_info(),
                raw_meta={
                    "backend": self.name,
                    "host": self._host,
                    "port": self._port_num,
                    "serial": self._device_serial,
                },
            )
        except ScpiError as e:
            raise BackendError(f"LibreVNA read failed: {e}") from e

    def device_info(self) -> str:
        parts = [self.name]
        if self._device_serial:
            parts.append(self._device_serial)
        parts.append(f"@ {self._host}:{self._port_num}")
        return " ".join(parts)

    def load_calibration(self, cal_path: str) -> bool:
        """Load a saved .cal file on the device. Returns True on success."""
        self._require_client()
        assert self._client is not None
        try:
            result = self._client.query_bool(
                f':VNA:CAL:LOAD? "{cal_path}"'
            )
            return result
        except ScpiError:
            return False

    def active_calibration(self) -> str:
        """Return the name of the active calibration, or empty string."""
        if self._client is None or not self._client.connected:
            return ""
        try:
            return self._client.query(":VNA:CAL:ACTIVE?").strip()
        except ScpiError:
            return ""

    # -------------------------------------------------- auto-launch helpers

    def auto_launch_gui(self, host: str = "localhost", port: int = 19542) -> bool:
        """Try to auto-launch LibreVNA-GUI if the SCPI port is not open.

        Returns True if the port is reachable after the attempt.
        """
        self._launcher = LibreVnaLauncher(host=host, port=port)
        return self._launcher.ensure_running()

    def stop_launched_gui(self) -> None:
        """Stop the LibreVNA-GUI subprocess if we launched it."""
        if self._launcher is not None:
            self._launcher.stop()
            self._launcher = None

    # -------------------------------------------------- internals

    def _ensure_traces(self) -> None:
        """Make sure S11 and S21 traces exist on the device."""
        if self._client is None:
            return
        try:
            existing_str = self._client.query(":VNA:TRAC:LIST?")
            existing = {
                s.strip().upper()
                for s in existing_str.split(",")
                if s.strip()
            }
        except ScpiError:
            existing = set()
        for param in ("S11", "S21"):
            try:
                if param not in existing:
                    self._client.write(f":VNA:TRAC:NEW {param}")
                self._client.write(f":VNA:TRAC:PAR {param} {param}")
            except ScpiError:
                pass

    @staticmethod
    def _parse_endpoint(endpoint: str) -> Tuple[str, int]:
        """Parse 'host:port' or 'host' into (host, port)."""
        endpoint = endpoint.strip()
        if ":" in endpoint:
            parts = endpoint.rsplit(":", 1)
            try:
                return parts[0], int(parts[1])
            except ValueError:
                pass
        return endpoint or "localhost", 19542

    def _require_client(self) -> None:
        if self._client is None or not self._client.connected:
            raise BackendError("LibreVNA SCPI client is not connected")
