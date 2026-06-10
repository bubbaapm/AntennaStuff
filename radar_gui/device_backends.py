"""Custom serial backends for LiteVNA and NanoVNA devices."""
from __future__ import annotations

import struct
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import serial
from serial.tools import list_ports

from .models import SweepConfig, SweepFrame


CMD_READFIFO = 0x18
CMD_WRITE1 = 0x20
CMD_WRITE2 = 0x21
CMD_WRITE8 = 0x23
ADDR_SWEEP_START = 0x00
ADDR_SWEEP_STEP = 0x10
ADDR_SWEEP_POINTS = 0x20
ADDR_SWEEP_VALS_PER_FREQ = 0x22
ADDR_RAW_SAMPLES_MODE = 0x26
ADDR_VALUES_FIFO = 0x30
ADDR_TX_POWER = 0x42
RAW_MODE_CALIBRATED = 0x03
RAW_MODE_RELEASE = 0x02
MAX_TX_POWER = 0x03
SAMPLE_STRUCT = struct.Struct("<iiiiiiH5sB")
SAMPLE_SIZE = 32


class BackendError(RuntimeError):
    """Base error for VNA backend operations."""


class BackendTimeout(BackendError):
    """Raised when a backend cannot read a complete response in time."""


@dataclass(frozen=True)
class SerialPortInfo:
    port: str
    description: str
    hwid: str = ""

    def label(self) -> str:
        return f"{self.port} - {self.description}" if self.description else self.port


def list_serial_ports() -> list[SerialPortInfo]:
    return [
        SerialPortInfo(port=p.device, description=p.description or "", hwid=p.hwid or "")
        for p in list_ports.comports()
    ]


def _read_exact(ser: serial.Serial, size: int, timeout_s: float) -> bytes:
    data = bytearray()
    deadline = time.monotonic() + timeout_s
    while len(data) < size and time.monotonic() < deadline:
        chunk = ser.read(size - len(data))
        if chunk:
            data.extend(chunk)
        else:
            time.sleep(0.002)
    if len(data) != size:
        raise BackendTimeout(f"Expected {size} bytes, got {len(data)}")
    return bytes(data)


def _safe_div(num: complex, den: complex) -> complex:
    return 0j if den == 0 else num / den


def parse_litevna_samples(data: bytes, points: int) -> tuple[np.ndarray, np.ndarray]:
    """Parse LiteVNA/NanoVNA-V2 32-byte raw samples into S11/S21 arrays."""
    expected = int(points) * SAMPLE_SIZE
    if len(data) != expected:
        raise BackendError(f"Expected {expected} sample bytes, got {len(data)}")
    s11 = np.zeros(points, dtype=np.complex128)
    s21 = np.zeros(points, dtype=np.complex128)
    for idx in range(points):
        sample = SAMPLE_STRUCT.unpack(data[idx * SAMPLE_SIZE : (idx + 1) * SAMPLE_SIZE])
        fwd = complex(sample[0], sample[1])
        refl = complex(sample[2], sample[3])
        thru = complex(sample[4], sample[5])
        freq_index = int(sample[6])
        if 0 <= freq_index < points:
            s11[freq_index] = _safe_div(refl, fwd)
            s21[freq_index] = _safe_div(thru, fwd)
    return s11, s21


def parse_complex_lines(lines: Iterable[str]) -> np.ndarray:
    values = []
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        values.append(complex(float(parts[0]), float(parts[1])))
    return np.asarray(values, dtype=np.complex128)


def parse_frequency_lines(lines: Iterable[str]) -> np.ndarray:
    values = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        first = line.split()[0]
        values.append(float(first))
    return np.asarray(values, dtype=float)


class DeviceBackend(ABC):
    name = "Device"

    def __init__(self) -> None:
        self.port = ""
        self._config = SweepConfig()

    @abstractmethod
    def connect(self, port: str) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def configure_sweep(self, config: SweepConfig) -> None: ...

    @abstractmethod
    def read_sweep(self) -> SweepFrame: ...

    @abstractmethod
    def device_info(self) -> str: ...

    def safe_release(self) -> None:
        pass


class LiteVnaBackend(DeviceBackend):
    name = "LiteVNA / NanoVNA V2"

    def __init__(self, baudrate: int = 115200, timeout: float = 0.1) -> None:
        super().__init__()
        self._baudrate = baudrate
        self._timeout = timeout
        self._ser: Optional[serial.Serial] = None

    def connect(self, port: str) -> None:
        self.port = port
        self._ser = serial.Serial(port, self._baudrate, timeout=self._timeout)
        self._sync()

    def disconnect(self) -> None:
        try:
            self.safe_release()
        finally:
            if self._ser is not None:
                self._ser.close()
            self._ser = None

    def safe_release(self) -> None:
        if self._ser is None or not self._ser.is_open:
            return
        try:
            self._ser.write(b"\x00" * 8)
            self._ser.write(struct.pack("<BBB", CMD_WRITE1, ADDR_RAW_SAMPLES_MODE, RAW_MODE_RELEASE))
            time.sleep(0.05)
        except Exception:
            pass

    def configure_sweep(self, config: SweepConfig) -> None:
        self._require_serial()
        self._config = config
        step_hz = int((config.stop_hz - config.start_hz) / max(1, config.points - 1))
        assert self._ser is not None
        self._sync()
        self._ser.write(struct.pack("<BBB", CMD_WRITE1, ADDR_RAW_SAMPLES_MODE, RAW_MODE_CALIBRATED))
        if config.power == "max":
            self._ser.write(struct.pack("<BBB", CMD_WRITE1, ADDR_TX_POWER, MAX_TX_POWER))
        self._ser.write(struct.pack("<BBQ", CMD_WRITE8, ADDR_SWEEP_START, int(config.start_hz)))
        self._ser.write(struct.pack("<BBQ", CMD_WRITE8, ADDR_SWEEP_STEP, step_hz))
        self._ser.write(struct.pack("<BBH", CMD_WRITE2, ADDR_SWEEP_POINTS, int(config.points)))
        self._ser.write(struct.pack("<BBH", CMD_WRITE2, ADDR_SWEEP_VALS_PER_FREQ, 1))
        self._ser.write(struct.pack("<BBB", CMD_WRITE1, ADDR_VALUES_FIFO, 0))
        time.sleep(0.1)

    def read_sweep(self) -> SweepFrame:
        self._require_serial()
        assert self._ser is not None
        self._ser.write(struct.pack("<BBB", CMD_READFIFO, ADDR_VALUES_FIFO, 0))
        data = _read_exact(self._ser, self._config.points * SAMPLE_SIZE, timeout_s=2.0)
        s11, s21 = parse_litevna_samples(data, self._config.points)
        return SweepFrame(
            freq_hz=self._config.frequency_axis(),
            s11=s11,
            s21=s21,
            timestamp=time.time(),
            device_id=self.device_info(),
            raw_meta={"backend": self.name, "port": self.port},
        )

    def device_info(self) -> str:
        return f"{self.name} on {self.port}" if self.port else self.name

    def _sync(self) -> None:
        if self._ser is not None:
            self._ser.write(b"\x00" * 8)
            time.sleep(0.05)

    def _require_serial(self) -> None:
        if self._ser is None or not self._ser.is_open:
            raise BackendError("Serial port is not connected")


class NanoVnaShellBackend(DeviceBackend):
    name = "NanoVNA Shell"

    def __init__(self, baudrate: int = 115200, timeout: float = 0.08) -> None:
        super().__init__()
        self._baudrate = baudrate
        self._timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._last_info = ""

    def connect(self, port: str) -> None:
        self.port = port
        self._ser = serial.Serial(port, self._baudrate, timeout=self._timeout)
        self._drain()
        try:
            self._last_info = "\n".join(self._exec("info", wait_s=0.05))
        except Exception:
            self._last_info = self.name

    def disconnect(self) -> None:
        if self._ser is not None:
            try:
                self._exec("resume", wait_s=0.02)
            except Exception:
                pass
            self._ser.close()
        self._ser = None

    def configure_sweep(self, config: SweepConfig) -> None:
        self._require_serial()
        self._config = config
        method = str(config.backend_options.get("sweep_method", "sweep")).strip() or "sweep"
        if method not in {"sweep", "scan"}:
            method = "sweep"
        list(self._exec(f"{method} {int(config.start_hz)} {int(config.stop_hz)} {int(config.points)}"))

    def read_sweep(self) -> SweepFrame:
        self._require_serial()
        freq = parse_frequency_lines(self._exec("frequencies"))
        s11 = parse_complex_lines(self._exec("data 0"))
        s21 = parse_complex_lines(self._exec("data 1"))
        if not (freq.size == s11.size == s21.size == self._config.points):
            raise BackendError(
                f"NanoVNA returned mismatched lengths: f={freq.size}, s11={s11.size}, s21={s21.size}"
            )
        return SweepFrame(
            freq_hz=freq,
            s11=s11,
            s21=s21,
            timestamp=time.time(),
            device_id=self.device_info(),
            raw_meta={"backend": self.name, "port": self.port},
        )

    def device_info(self) -> str:
        if self._last_info:
            first = self._last_info.splitlines()[0]
            return f"{first} on {self.port}"
        return f"{self.name} on {self.port}" if self.port else self.name

    def _exec(self, command: str, wait_s: float = 0.05) -> list[str]:
        self._require_serial()
        assert self._ser is not None
        self._drain()
        self._ser.write(f"{command}\r".encode("ascii"))
        time.sleep(wait_s)
        lines = []
        empty = 0
        while empty < 80:
            raw = self._ser.readline()
            if not raw:
                empty += 1
                continue
            line = raw.decode("ascii", errors="replace").strip()
            if not line or line == command:
                continue
            if line.startswith("ch>"):
                return lines
            lines.append(line)
        raise BackendTimeout(f"Timed out waiting for NanoVNA command: {command}")

    def _drain(self) -> None:
        if self._ser is None:
            return
        old_timeout = self._ser.timeout
        self._ser.timeout = 0.02
        try:
            for _ in range(64):
                if not self._ser.read(128):
                    break
        finally:
            self._ser.timeout = old_timeout

    def _require_serial(self) -> None:
        if self._ser is None or not self._ser.is_open:
            raise BackendError("Serial port is not connected")


def make_backend(name: str) -> DeviceBackend:
    key = name.strip().lower()
    if "shell" in key or key == "nanovna":
        return NanoVnaShellBackend()
    if "libre" in key or "scpi" in key:
        from .librevna_backend import LibreVnaScpiBackend
        return LibreVnaScpiBackend()
    return LiteVnaBackend()
