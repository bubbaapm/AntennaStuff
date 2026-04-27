"""
Tiny SCPI-over-TCP client for LibreVNA-GUI.

LibreVNA-GUI runs an SCPI server on TCP (default port 19542). Commands and
responses are newline-terminated text. Queries end with '?'. The server can
be lossy if you slam it with overlapping queries — we serialize via a Lock.
"""
from __future__ import annotations
import socket
import threading
from typing import Optional


class ScpiError(RuntimeError):
    pass


class ScpiClient:
    """
    Minimal blocking SCPI client. Thread-safe (one socket, one lock).

    Use from a worker thread (QThread/QRunnable) — never directly from the
    Qt main thread for anything that takes more than a couple of ms.
    """

    def __init__(self, host: str = "localhost", port: int = 19542,
                 timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._rx_buf = b""

    # ------------------------------------------------------------- low level
    def connect(self) -> None:
        with self._lock:
            self._connect_locked()

    def _connect_locked(self) -> None:
        if self._sock is not None:
            return
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        self._sock = s
        self._rx_buf = b""

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            self._rx_buf = b""

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # --------------------------------------------------------------- core IO
    def _send_locked(self, data: str) -> None:
        if self._sock is None:
            raise ScpiError("not connected")
        payload = data.encode("ascii") + b"\n"
        try:
            self._sock.sendall(payload)
        except (OSError, socket.timeout) as e:
            self.close_locked()
            raise ScpiError(f"send failed: {e}") from e

    def _readline_locked(self) -> str:
        if self._sock is None:
            raise ScpiError("not connected")
        while b"\n" not in self._rx_buf:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout as e:
                raise ScpiError("read timeout") from e
            except OSError as e:
                self.close_locked()
                raise ScpiError(f"read failed: {e}") from e
            if not chunk:
                self.close_locked()
                raise ScpiError("connection closed by peer")
            self._rx_buf += chunk
        line, _, rest = self._rx_buf.partition(b"\n")
        self._rx_buf = rest
        return line.decode("ascii", errors="replace").rstrip("\r")

    def close_locked(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._rx_buf = b""

    # --------------------------------------------------------------- public
    def write(self, cmd: str) -> None:
        """Send a command; do not wait for a reply."""
        with self._lock:
            self._connect_locked()
            self._send_locked(cmd)

    def query(self, cmd: str) -> str:
        """Send a query (must end with '?') and return the single-line reply."""
        if "?" not in cmd:
            raise ScpiError(f"query must contain '?': {cmd!r}")
        with self._lock:
            self._connect_locked()
            # Drain any stale buffered data — defensive.
            self._rx_buf = b""
            self._send_locked(cmd)
            return self._readline_locked()

    def set_timeout(self, seconds: float) -> None:
        self.timeout = seconds
        if self._sock is not None:
            try:
                self._sock.settimeout(seconds)
            except OSError:
                pass

    # ------------------------------------------------------------- helpers
    def query_bool(self, cmd: str) -> bool:
        v = self.query(cmd).strip().upper()
        return v in ("TRUE", "1", "ON", "YES")

    def query_float(self, cmd: str) -> float:
        return float(self.query(cmd).strip())

    def query_int(self, cmd: str) -> int:
        return int(float(self.query(cmd).strip()))
