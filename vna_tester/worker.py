"""
Background workers for sweep polling and calibration measurement.

We share the controller's ScpiClient — its internal lock makes that safe
across threads. This avoids fighting with LibreVNA-GUI for a second TCP
connection and keeps everything coherent. The worker only holds the lock
for milliseconds at a time, so UI clicks aren't visibly delayed.
"""
from __future__ import annotations
import time
from typing import List, Optional

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from .controller import _parse_trace_data
from .scpi import ScpiClient, ScpiError


class SweepWorker(QObject):
    """
    Polls the device, emits trace_received for each S-parameter, and
    forwards averaging progress. Pulls trace data on every cycle so we
    work the same whether the device is in continuous mode (FIN bounces
    fast), single-sweep mode (FIN sits TRUE), or paused.
    """

    traces_batch = pyqtSignal(dict)                    # {name: (freq, s)} — one per poll
    progress = pyqtSignal(int, int)                    # avg_current, avg_target
    sweep_done = pyqtSignal()
    error = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, client: ScpiClient, parameters: List[str],
                 poll_interval_s: float = 0.25):
        super().__init__()
        self._client = client
        self._parameters = list(parameters)
        self._poll = poll_interval_s
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def update_parameters(self, parameters: List[str]) -> None:
        self._parameters = list(parameters)

    def run(self) -> None:
        consec_errors = 0
        while not self._stop:
            if not self._client.connected:
                # wait quietly for the main thread to (re)connect
                self._sleep_with_stop(self._poll)
                continue

            had_error = False

            # Averaging progress (cheap)
            try:
                cur = self._client.query_int(":VNA:ACQ:AVGLEV?")
                tgt = max(1, self._client.query_int(":VNA:ACQ:AVG?"))
                self.progress.emit(cur, tgt)
            except ScpiError:
                pass

            # Pull each trace. We always pull — relying on FIN edges fails
            # when avg=1 (FIN stays TRUE) and during single-sweep mode.
            batch: dict = {}
            for p in self._parameters:
                if self._stop:
                    break
                try:
                    payload = self._client.query(f":VNA:TRAC:DATA? {p}")
                except ScpiError as e:
                    had_error = True
                    self.error.emit(f"trace {p}: {e}")
                    break
                try:
                    f, s = _parse_trace_data(payload)
                except Exception as e:
                    self.error.emit(f"parse {p}: {e}")
                    continue
                if f.size > 0:
                    batch[p] = (f, s)

            if batch:
                # ONE Qt signal per poll cycle — not one per trace.
                # Saves 4× the signal-cascade work in the UI.
                self.traces_batch.emit(batch)

            if had_error:
                consec_errors += 1
                if consec_errors > 8:
                    self.error.emit("too many SCPI errors, sweep worker stopping")
                    break
            else:
                consec_errors = 0
                self.sweep_done.emit()

            self._sleep_with_stop(self._poll)

        self.stopped.emit()

    def _sleep_with_stop(self, total_s: float) -> None:
        """Sleep in small slices so stop() reacts within ~20 ms."""
        deadline = time.monotonic() + total_s
        while not self._stop and time.monotonic() < deadline:
            time.sleep(0.02)


class CalMeasureWorker(QObject):
    """
    Tells the device to measure a calibration step, then polls
    VNA:CAL:BUSY? until it returns FALSE. Uses the shared client.
    """

    finished = pyqtSignal(bool)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client: ScpiClient, indices: List[int],
                 description: str = ""):
        super().__init__()
        self._client = client
        self._indices = list(indices)
        self._desc = description

    def run(self) -> None:
        try:
            self.progress.emit(f"Measuring {self._desc}…")
            self._client.write(":VNA:CAL:MEAS " + ",".join(str(i) for i in self._indices))
            # Wait for BUSY to actually flip TRUE before polling for FALSE.
            # MEAS is fire-and-forget; if we poll BUSY too eagerly we read
            # the pre-MEAS idle state and falsely conclude the measurement
            # already finished — so the step appears to "run instantly"
            # without ever capturing data. Block here until the device
            # acknowledges it's busy (or a sane startup timeout).
            started = False
            for _ in range(60):  # ~3 s at 50 ms
                time.sleep(0.05)
                try:
                    if self._client.query_bool(":VNA:CAL:BUSY?"):
                        started = True
                        break
                except ScpiError as e:
                    self.error.emit(str(e))
                    self.finished.emit(False)
                    return
            if not started:
                self.error.emit(
                    "VNA never reported busy after :VNA:CAL:MEAS — the "
                    "measurement did not run. Check the device connection "
                    "and try again."
                )
                self.finished.emit(False)
                return
            for _ in range(2400):  # up to ~2 minutes @ 50 ms
                time.sleep(0.05)
                try:
                    if not self._client.query_bool(":VNA:CAL:BUSY?"):
                        break
                except ScpiError as e:
                    self.error.emit(str(e))
                    self.finished.emit(False)
                    return
            else:
                self.error.emit("calibration measurement timed out")
                self.finished.emit(False)
                return
            self.finished.emit(True)
        except ScpiError as e:
            self.error.emit(str(e))
            self.finished.emit(False)


def run_in_thread(worker: QObject) -> QThread:
    th = QThread()
    worker.moveToThread(th)
    th.started.connect(worker.run)
    th.start()
    return th
