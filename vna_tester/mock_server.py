"""
Mock LibreVNA-GUI SCPI server.

Fakes enough of the SCPI surface for the VNA Tester app to exercise its
sweep, marker, calibration, and export paths without real hardware. Run:

    python -m vna_tester.mock_server [--port 19542]

It generates a synthetic patch-antenna-like S11 dip near 2.45 GHz so the
metrics panel shows realistic numbers and the markers find a peak/min.

The mock keeps internal sweep state (start/stop/points/IFBW/avg/run),
toggles a fake AVGLEV counter on each sweep so the worker sees fresh
data each poll, and returns valid Touchstone-style trace payloads.
"""
from __future__ import annotations
import argparse
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np


@dataclass
class MockState:
    start_hz: float = 100e6
    stop_hz: float = 6e9
    points: int = 501
    ifbw_hz: float = 10_000.0
    avg_target: int = 1
    avg_level: int = 0
    power_dbm: float = -10.0
    running: bool = True
    single: bool = False
    fin: bool = True
    cal_type: str = ""                          # active cal token
    cal_measurements: List[Tuple[str, int]] = field(default_factory=list)
    cal_busy: bool = False
    devices: List[str] = field(default_factory=lambda: ["MOCK001-1234567"])
    connected_serial: str = "MOCK001-1234567"
    sweep_counter: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


def _model_s11(freq: np.ndarray, jitter: float = 0.0) -> np.ndarray:
    """Patch-antenna-shaped S11 dip near 2.45 GHz for realism."""
    f0 = 2.45e9
    bw = 100e6
    # Lorentzian-ish dip in linear magnitude
    x = (freq - f0) / bw
    mag = 1.0 - 0.93 / (1.0 + x**2)
    # add a little spectral wiggle so traces are not flat
    mag = mag * (1.0 + 0.005 * np.sin(2 * np.pi * freq / 600e6))
    if jitter > 0:
        mag = mag * (1.0 + jitter * (np.random.rand(freq.size) - 0.5))
        mag = np.clip(mag, 0.0, 1.0)
    phase = -2 * np.pi * freq * 1.5e-9 + 0.4 * np.sin(2 * np.pi * (freq - f0) / 800e6)
    return mag * np.exp(1j * phase)


def _model_s21(freq: np.ndarray, jitter: float = 0.0) -> np.ndarray:
    """Mostly-flat thru with a roll-off at the high end."""
    rolloff = 1.0 / (1.0 + (freq / 8e9) ** 4)
    mag = 0.05 + 0.85 * rolloff
    phase = -2 * np.pi * freq * 1.0e-9
    s = mag * np.exp(1j * phase)
    if jitter > 0:
        s = s + jitter * (np.random.randn(freq.size) + 1j * np.random.randn(freq.size)) * 0.01
    return s


def _trace_payload(freq: np.ndarray, s: np.ndarray) -> str:
    parts: List[str] = []
    for f, c in zip(freq, s):
        parts.append(f"{f:.6e},{c.real:.6e},{c.imag:.6e}")
    return ",".join(parts)


class MockHandler(socketserver.StreamRequestHandler):
    state: MockState = None  # type: ignore  (assigned by the server class)

    def handle(self) -> None:
        client_ip = self.client_address[0]
        print(f"[mock] client connected: {client_ip}", file=sys.stderr)
        try:
            for raw in self.rfile:
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                reply = self._dispatch(line)
                if reply is not None:
                    self.wfile.write((reply + "\n").encode("ascii"))
        except (ConnectionResetError, BrokenPipeError):
            pass
        print(f"[mock] client disconnected: {client_ip}", file=sys.stderr)

    # ----------------------------------------------------------- dispatch
    def _dispatch(self, line: str) -> str | None:
        st = self.state
        cmd = line
        # Strip leading colon
        if cmd.startswith(":"):
            cmd = cmd[1:]
        upper = cmd.upper()

        # IDN
        if upper == "*IDN?":
            return "Mock VNA Tester v1.0,LibreVNA-MOCK"

        # device
        if upper == "DEV:LIST?":
            return ",".join(st.devices)
        if upper.startswith("DEV:CONN"):
            if upper.endswith("?"):
                return st.connected_serial or "Not connected"
            parts = cmd.split(maxsplit=1)
            if len(parts) > 1:
                st.connected_serial = parts[1].strip()
            elif st.devices:
                st.connected_serial = st.devices[0]
            return None
        if upper == "DEV:DISC":
            st.connected_serial = ""
            return None
        if upper.startswith("DEV:MODE"):
            return None
        if upper.startswith("DEV:INFO?") or upper.startswith("DEV:INF?"):
            return "MockHardware,FW1.0,Serial=" + (st.connected_serial or "n/a")

        # frequency
        if upper.startswith("VNA:FREQ:START"):
            return self._setget_float(cmd, "start_hz")
        if upper.startswith("VNA:FREQ:STOP"):
            return self._setget_float(cmd, "stop_hz")
        if upper.startswith("VNA:FREQ:CENT"):
            if upper.endswith("?"):
                return f"{0.5*(st.start_hz+st.stop_hz):.6f}"
            v = self._arg_float(cmd)
            if v is not None:
                span = st.stop_hz - st.start_hz
                st.start_hz = max(0.0, v - 0.5 * span)
                st.stop_hz = v + 0.5 * span
            return None
        if upper.startswith("VNA:FREQ:SPAN"):
            if upper.endswith("?"):
                return f"{(st.stop_hz - st.start_hz):.6f}"
            v = self._arg_float(cmd)
            if v is not None:
                center = 0.5 * (st.start_hz + st.stop_hz)
                st.start_hz = max(0.0, center - 0.5 * v)
                st.stop_hz = center + 0.5 * v
            return None

        # acquisition
        if upper.startswith("VNA:ACQ:POINTS"):
            if upper.endswith("?"):
                return str(st.points)
            v = self._arg_int(cmd)
            if v is not None:
                st.points = max(2, v)
            return None
        if upper.startswith("VNA:ACQ:IFBW"):
            return self._setget_float(cmd, "ifbw_hz")
        if upper.startswith("VNA:ACQ:AVGLEV"):
            return str(st.avg_level)
        if upper.startswith("VNA:ACQ:AVG"):
            if upper.endswith("?"):
                return str(st.avg_target)
            v = self._arg_int(cmd)
            if v is not None:
                st.avg_target = max(1, v)
            return None
        if upper.startswith("VNA:ACQ:SINGLE"):
            if upper.endswith("?"):
                return "TRUE" if st.single else "FALSE"
            tok = cmd.split(maxsplit=1)
            if len(tok) > 1:
                st.single = tok[1].strip().upper() in ("TRUE", "1", "ON", "YES")
            return None
        if upper.startswith("VNA:ACQ:RUN"):
            if upper.endswith("?"):
                return "TRUE" if st.running else "FALSE"
            tok = cmd.split(maxsplit=1)
            if len(tok) > 1:
                st.running = tok[1].strip().upper() in ("TRUE", "1", "ON", "YES")
                if st.running:
                    # advance our fake sweep
                    st.sweep_counter += 1
                    st.avg_level = min(st.avg_level + 1, st.avg_target)
            return None
        if upper == "VNA:ACQ:STOP":
            st.running = False
            return None
        if upper.startswith("VNA:ACQ:FIN"):
            return "TRUE"

        # stimulus
        if upper.startswith("VNA:STIM:LVL"):
            return self._setget_float(cmd, "power_dbm")

        # traces
        if upper.startswith("VNA:TRAC:LIST"):
            return "S11,S12,S21,S22"
        if upper.startswith("VNA:TRAC:NEW"):
            return None
        if upper.startswith("VNA:TRAC:PAR"):
            return None
        if upper.startswith("VNA:TRAC:DATA?"):
            # advance sweep counter so plots show motion
            with st.lock:
                if st.running:
                    st.sweep_counter += 1
                    st.avg_level = min(st.avg_level + 1, st.avg_target)
            tok = cmd.split(None, 1)
            param = tok[1].strip() if len(tok) > 1 else "S11"
            freq = np.linspace(st.start_hz, st.stop_hz, st.points)
            jitter = 0.02 if st.running else 0.0
            if param.upper() == "S21" or param.upper() == "S12":
                s = _model_s21(freq, jitter=jitter)
            else:
                s = _model_s11(freq, jitter=jitter)
            return _trace_payload(freq, s)
        if upper.startswith("VNA:TRAC:TOUCH?"):
            tok = cmd.split(None, 1)
            names = [n.strip() for n in (tok[1] if len(tok) > 1 else "S11").split(",") if n.strip()]
            freq = np.linspace(st.start_hz, st.stop_hz, st.points)
            lines = ["# HZ S RI R 50"]
            cols = []
            for n in names:
                cols.append(_model_s21(freq) if n.upper() in ("S21", "S12") else _model_s11(freq))
            for i, f in enumerate(freq):
                row = [f"{f:.6e}"]
                for c in cols:
                    row.append(f"{c[i].real:.6e} {c[i].imag:.6e}")
                lines.append(" ".join(row))
            return "\n".join(lines)

        # calibration
        if upper.startswith("VNA:CAL:RESET"):
            st.cal_measurements.clear()
            st.cal_type = ""
            return None
        if upper.startswith("VNA:CAL:NUM"):
            return str(len(st.cal_measurements))
        if upper.startswith("VNA:CAL:ADD"):
            tok = cmd.split(maxsplit=1)
            if len(tok) > 1:
                std = tok[1].strip().split()[0].upper()
                st.cal_measurements.append((std, 1))
            return None
        if upper.startswith("VNA:CAL:PORT"):
            return None
        if upper.startswith("VNA:CAL:STAND"):
            return None
        if upper.startswith("VNA:CAL:MEAS"):
            # simulate a brief measurement
            def _measure():
                with st.lock:
                    st.cal_busy = True
                time.sleep(0.5)
                with st.lock:
                    st.cal_busy = False
            threading.Thread(target=_measure, daemon=True).start()
            return None
        if upper.startswith("VNA:CAL:BUSY"):
            return "TRUE" if st.cal_busy else "FALSE"
        if upper.startswith("VNA:CAL:ACT"):
            if upper.endswith("?"):
                return st.cal_type or "NONE"
            tok = cmd.split(maxsplit=1)
            if len(tok) > 1:
                st.cal_type = tok[1].strip()
            return None
        if upper.startswith("VNA:CAL:ACTIVE"):
            return st.cal_type or "NONE"
        if upper.startswith("VNA:CAL:SAVE"):
            return None
        if upper.startswith("VNA:CAL:LOAD"):
            return "TRUE"

        # default: silent ack
        return None

    # ----------------------------------------------------------- helpers
    def _arg_float(self, cmd: str) -> float | None:
        tok = cmd.split(maxsplit=1)
        if len(tok) <= 1:
            return None
        try:
            return float(tok[1].strip())
        except ValueError:
            return None

    def _arg_int(self, cmd: str) -> int | None:
        v = self._arg_float(cmd)
        return None if v is None else int(v)

    def _setget_float(self, cmd: str, attr: str) -> str | None:
        if cmd.upper().endswith("?"):
            return f"{getattr(self.state, attr):.6f}"
        v = self._arg_float(cmd)
        if v is not None:
            setattr(self.state, attr, v)
        return None


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def run(port: int = 19542) -> None:
    state = MockState()
    handler = type("Bound", (MockHandler,), {"state": state})
    server = ThreadingTCPServer(("127.0.0.1", port), handler)
    print(f"[mock] listening on 127.0.0.1:{port} — Ctrl+C to quit", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[mock] shutting down", file=sys.stderr)
    finally:
        server.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(description="Mock LibreVNA-GUI SCPI server.")
    ap.add_argument("--port", type=int, default=19542)
    args = ap.parse_args()
    run(args.port)


if __name__ == "__main__":
    main()
