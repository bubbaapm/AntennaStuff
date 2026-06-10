"""Qt worker for continuous VNA polling."""
from __future__ import annotations

import time

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.sip import isdeleted

from .device_backends import BackendError, make_backend
from .models import SweepConfig


class VnaWorker(QObject):
    frame_received = pyqtSignal(object)
    connected = pyqtSignal(str)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, backend_name: str, port: str, config: SweepConfig):
        super().__init__()
        self._backend_name = backend_name
        self._port = port
        self._config = config
        self._stop = False
        self._backend = None

    def stop(self) -> None:
        self._stop = True
        try:
            if self._backend is not None:
                self._backend.disconnect()
        except Exception:
            pass

    def run(self) -> None:
        self._backend = make_backend(self._backend_name)
        try:
            if isdeleted(self):
                return
            self.status.emit(f"Connecting to {self._port}...")
            self._backend.connect(self._port)
            if isdeleted(self):
                return
            self._backend.configure_sweep(self._config)
            if isdeleted(self):
                return
            self.connected.emit(self._backend.device_info())
            
            # Allow the first sweep to start/complete before we poll
            self._sleep_with_stop(0.2)
            
            consec_errors = 0
            while True:
                if isdeleted(self) or self._stop:
                    break
                try:
                    frame = self._backend.read_sweep()
                    if isdeleted(self) or self._stop:
                        break
                    self.frame_received.emit(frame)
                    consec_errors = 0
                except Exception as exc:
                    if isdeleted(self) or self._stop:
                        break
                    consec_errors += 1
                    if not isdeleted(self):
                        self.error.emit(f"Poll error ({consec_errors}/10): {exc}")
                    if consec_errors >= 10:
                        raise exc
                    self._sleep_with_stop(0.2)
                
                if isdeleted(self) or self._stop:
                    break
                delay = max(0.0, float(self._config.poll_delay_s))
                if delay:
                    self._sleep_with_stop(delay)
        except Exception as exc:
            if not isdeleted(self) and not self._stop:
                self.error.emit(str(exc))
            try:
                if self._backend is not None:
                    self._backend.safe_release()
            except Exception:
                pass
        finally:
            try:
                if self._backend is not None:
                    self._backend.disconnect()
            except Exception as exc:
                if not isdeleted(self) and not self._stop:
                    self.error.emit(f"Disconnect cleanup failed: {exc}")
            if not isdeleted(self):
                self.stopped.emit()

    def _sleep_with_stop(self, total_s: float) -> None:
        deadline = time.monotonic() + total_s
        while not isdeleted(self) and not self._stop and time.monotonic() < deadline:
            time.sleep(0.01)
