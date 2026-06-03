"""Qt worker for continuous VNA polling."""
from __future__ import annotations

import time

from PyQt6.QtCore import QObject, pyqtSignal

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

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        backend = make_backend(self._backend_name)
        try:
            self.status.emit(f"Connecting to {self._port}...")
            backend.connect(self._port)
            backend.configure_sweep(self._config)
            self.connected.emit(backend.device_info())
            while not self._stop:
                frame = backend.read_sweep()
                self.frame_received.emit(frame)
                delay = max(0.0, float(self._config.poll_delay_s))
                if delay:
                    self._sleep_with_stop(delay)
        except Exception as exc:
            self.error.emit(str(exc))
            try:
                backend.safe_release()
            except Exception:
                pass
        finally:
            try:
                backend.disconnect()
            except Exception as exc:
                self.error.emit(f"Disconnect cleanup failed: {exc}")
            self.stopped.emit()

    def _sleep_with_stop(self, total_s: float) -> None:
        deadline = time.monotonic() + total_s
        while not self._stop and time.monotonic() < deadline:
            time.sleep(0.01)
