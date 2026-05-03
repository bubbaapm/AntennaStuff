"""
VnaController — high-level wrapper around the SCPI client.

This object lives in the Qt main thread and emits signals. The actual
SCPI socket I/O is dispatched via a worker thread (see worker.py) so
sweep polling and calibration measurements never block the UI.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from .scpi import ScpiClient, ScpiError


# Touchstone-format trace tuple from VNA:TRAC:DATA?: "x,re,im,x,re,im,..."
_NUMERIC = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def _parse_trace_data(payload: str) -> Tuple[np.ndarray, np.ndarray]:
    nums = [float(m.group(0)) for m in _NUMERIC.finditer(payload)]
    if len(nums) % 3 != 0:
        # tolerate trailing junk
        nums = nums[: (len(nums) // 3) * 3]
    arr = np.asarray(nums, dtype=float).reshape(-1, 3)
    freq = arr[:, 0]
    s = arr[:, 1] + 1j * arr[:, 2]
    return freq, s


@dataclass
class SweepConfig:
    start_hz: float = 100e6
    stop_hz: float = 6e9
    points: int = 501
    ifbw_hz: float = 10_000.0
    averaging: int = 1
    power_dbm: float = -10.0


CAL_TYPES = ("None", "Port 1", "Port 2", "SOLT", "Through")
CAL_STANDARDS = ("OPEN", "SHORT", "LOAD", "THROUGH", "ISOLATION")


class VnaController(QObject):
    """
    Owns the SCPI socket. All public methods are safe to call from the
    Qt main thread but are *blocking* on the SCPI socket — for fast ops
    only (set/get a value). Long ops (sweep, calibration measure) should
    use the SweepWorker / CalWorker.
    """

    connected_changed = pyqtSignal(bool)
    error = pyqtSignal(str)
    info_message = pyqtSignal(str)

    def __init__(self, host: str = "localhost", port: int = 19542,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.client = ScpiClient(host=host, port=port, timeout=5.0)

    # ------------------------------------------------------------- conn
    @property
    def connected(self) -> bool:
        return self.client.connected

    def set_endpoint(self, host: str, port: int) -> None:
        was = self.client.connected
        self.client.close()
        self.client.host = host
        self.client.port = port
        if was:
            try:
                self.client.connect()
            except ScpiError as e:
                self.error.emit(str(e))
                self.connected_changed.emit(False)

    def connect_to_server(self) -> bool:
        try:
            self.client.connect()
            try:
                self.client.write(":DEV:MODE VNA")  # ensure VNA mode
            except ScpiError:
                pass
            self.connected_changed.emit(True)
            return True
        except ScpiError as e:
            self.error.emit(f"SCPI connect failed: {e}")
            self.connected_changed.emit(False)
            return False

    def disconnect(self) -> None:
        self.client.close()
        self.connected_changed.emit(False)

    # --------------------------------------------------------- device list
    def list_devices(self) -> List[str]:
        try:
            reply = self.client.query(":DEV:LIST?")
            return [s.strip() for s in reply.split(",") if s.strip()]
        except ScpiError as e:
            self.error.emit(str(e))
            return []

    def connected_serial(self) -> str:
        try:
            return self.client.query(":DEV:CONN?").strip()
        except ScpiError:
            return ""

    def connect_device(self, serial: str = "") -> bool:
        try:
            cmd = ":DEV:CONN" + (f" {serial}" if serial else "")
            self.client.write(cmd)
            return True
        except ScpiError as e:
            self.error.emit(str(e))
            return False

    def disconnect_device(self) -> None:
        try:
            self.client.write(":DEV:DISC")
        except ScpiError:
            pass

    def idn(self) -> str:
        try:
            return self.client.query("*IDN?").strip()
        except ScpiError:
            return ""

    # --------------------------------------------------------------- sweep
    def apply_sweep(self, cfg: SweepConfig) -> None:
        """Push the entire sweep config to the device."""
        c = self.client
        try:
            c.write(":VNA:ACQ:STOP")
            c.write(f":VNA:FREQ:START {cfg.start_hz:.6f}")
            c.write(f":VNA:FREQ:STOP {cfg.stop_hz:.6f}")
            c.write(f":VNA:ACQ:POINTS {int(cfg.points)}")
            c.write(f":VNA:ACQ:IFBW {cfg.ifbw_hz:.3f}")
            c.write(f":VNA:ACQ:AVG {max(1, int(cfg.averaging))}")
            c.write(f":VNA:STIM:LVL {cfg.power_dbm:.2f}")
            c.write(":VNA:ACQ:RUN TRUE")
        except ScpiError as e:
            self.error.emit(str(e))

    def read_sweep_config(self) -> SweepConfig:
        c = self.client
        try:
            return SweepConfig(
                start_hz=c.query_float(":VNA:FREQ:START?"),
                stop_hz=c.query_float(":VNA:FREQ:STOP?"),
                points=c.query_int(":VNA:ACQ:POINTS?"),
                ifbw_hz=c.query_float(":VNA:ACQ:IFBW?"),
                averaging=c.query_int(":VNA:ACQ:AVG?"),
                power_dbm=c.query_float(":VNA:STIM:LVL?"),
            )
        except ScpiError as e:
            self.error.emit(str(e))
            return SweepConfig()

    def set_run(self, run: bool) -> None:
        try:
            self.client.write(f":VNA:ACQ:RUN {'TRUE' if run else 'FALSE'}")
        except ScpiError as e:
            self.error.emit(str(e))

    def set_single(self, single: bool) -> None:
        try:
            self.client.write(f":VNA:ACQ:SINGLE {'TRUE' if single else 'FALSE'}")
        except ScpiError as e:
            self.error.emit(str(e))

    def acquisition_finished(self) -> bool:
        try:
            return self.client.query_bool(":VNA:ACQ:FIN?")
        except ScpiError:
            return False

    def averaging_progress(self) -> Tuple[int, int]:
        """Returns (current, target) sweeps for the moving-average filter."""
        try:
            cur = self.client.query_int(":VNA:ACQ:AVGLEV?")
            tgt = self.client.query_int(":VNA:ACQ:AVG?")
            return cur, tgt
        except ScpiError:
            return 0, 0

    # --------------------------------------------------------- traces
    def list_trace_names(self) -> List[str]:
        try:
            reply = self.client.query(":VNA:TRAC:LIST?")
            return [s.strip() for s in reply.split(",") if s.strip()]
        except ScpiError as e:
            self.error.emit(str(e))
            return []

    def ensure_default_traces(self) -> None:
        """
        Make sure traces named 'S11','S12','S21','S22' exist on the device
        and are mapped to the matching parameter. Idempotent.
        """
        existing = set(self.list_trace_names())
        for p in ("S11", "S12", "S21", "S22"):
            try:
                if p not in existing:
                    self.client.write(f":VNA:TRAC:NEW {p}")
                self.client.write(f":VNA:TRAC:PAR {p} {p}")
            except ScpiError as e:
                self.error.emit(str(e))

    def get_trace(self, name: str) -> Tuple[np.ndarray, np.ndarray]:
        """Returns (freq[N], S[N] complex) for the named trace."""
        try:
            payload = self.client.query(f":VNA:TRAC:DATA? {name}")
            return _parse_trace_data(payload)
        except ScpiError as e:
            self.error.emit(str(e))
            return np.array([]), np.array([], dtype=complex)

    def get_touchstone(self, names: List[str]) -> str:
        """
        Returns Touchstone-format text (Hz, S, real/imag, 50 Ω) for the
        listed traces. Trace count must be a perfect square (1 or 4).
        Built locally from per-trace VNA:TRAC:DATA? queries — LibreVNA's
        SCPI server has no single-shot Touchstone export, and its trace
        replies are line-based so a multi-line export wouldn't fit the
        single-line SCPI reply contract anyway.
        """
        if len(names) not in (1, 4):
            self.error.emit(f"Touchstone needs 1 or 4 traces, got {len(names)}")
            return ""
        freq_ref: Optional[np.ndarray] = None
        cols: List[np.ndarray] = []
        for name in names:
            f, s = self.get_trace(name)
            if f.size == 0:
                return ""
            if freq_ref is None:
                freq_ref = f
            elif f.shape != freq_ref.shape or not np.allclose(f, freq_ref):
                self.error.emit(f"Trace {name} freq grid differs from {names[0]}")
                return ""
            cols.append(s)
        assert freq_ref is not None
        lines = ["# Hz S RI R 50"]
        for i, f in enumerate(freq_ref):
            row = [f"{f:.0f}"]
            for c in cols:
                row.append(f"{c[i].real:.12g} {c[i].imag:.12g}")
            lines.append(" ".join(row))
        lines.append("")
        return "\n".join(lines)

    # -------------------------------------------------------- calibration
    def cal_active_type(self) -> str:
        try:
            return self.client.query(":VNA:CAL:ACTIVE?").strip()
        except ScpiError:
            return ""

    def cal_available_types(self) -> List[str]:
        try:
            reply = self.client.query(":VNA:CAL:ACT?")
            return [s.strip() for s in reply.split(",") if s.strip()]
        except ScpiError:
            return []

    def cal_activate(self, cal_type: str) -> None:
        try:
            self.client.write(f":VNA:CAL:ACT {cal_type}")
        except ScpiError as e:
            self.error.emit(str(e))

    def cal_reset(self) -> None:
        try:
            self.client.write(":VNA:CAL:RESET")
        except ScpiError as e:
            self.error.emit(str(e))

    def cal_count(self) -> int:
        try:
            return self.client.query_int(":VNA:CAL:NUM?")
        except ScpiError:
            return 0

    def cal_add(self, std_type: str, port: int = 1) -> int:
        """
        Add a measurement slot for std_type (OPEN/SHORT/LOAD/THROUGH/ISOLATION),
        bind it to a port, and return its 1-based index.
        """
        try:
            self.client.write(f":VNA:CAL:ADD {std_type}")
            n = self.cal_count()
            if std_type != "THROUGH" and std_type != "ISOLATION":
                self.client.write(f":VNA:CAL:PORT {n} {port}")
            return n
        except ScpiError as e:
            self.error.emit(str(e))
            return 0

    def cal_measure(self, indices: List[int]) -> None:
        try:
            self.client.write(":VNA:CAL:MEAS " + ",".join(str(i) for i in indices))
        except ScpiError as e:
            self.error.emit(str(e))

    def cal_busy(self) -> bool:
        try:
            return self.client.query_bool(":VNA:CAL:BUSY?")
        except ScpiError:
            return False

    def cal_save(self, filename: str) -> None:
        try:
            self.client.write(f':VNA:CAL:SAVE "{filename}"')
        except ScpiError as e:
            self.error.emit(str(e))

    def cal_load(self, filename: str) -> bool:
        try:
            return self.client.query_bool(f':VNA:CAL:LOAD? "{filename}"')
        except ScpiError as e:
            self.error.emit(str(e))
            return False
