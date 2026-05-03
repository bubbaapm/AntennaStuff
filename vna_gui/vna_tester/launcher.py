"""
Launch LibreVNA-GUI in the background so the SCPI server is up.

We spawn it with --no-gui (per upstream docs: the SCPI server is hosted by
LibreVNA-GUI; the flag suppresses the windowing). The subprocess is owned
by us — we kill it on app exit unless the user already had one running.
"""
from __future__ import annotations
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


def is_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class LibreVnaLauncher:
    """Wraps a LibreVNA-GUI subprocess. Idempotent — won't double-spawn."""

    def __init__(self, exe_path: Path, host: str = "localhost", port: int = 19542):
        self.exe_path = Path(exe_path)
        self.host = host
        self.port = port
        self._proc: Optional[subprocess.Popen] = None
        self._owned = False  # True if WE started it; we'll clean it up.

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ensure_running(self, wait_seconds: float = 8.0,
                       headless: bool = True) -> bool:
        """
        Make sure the SCPI port is reachable. If something is already
        listening, do nothing. Otherwise spawn LibreVNA-GUI ourselves.

        Returns True if the port is reachable when we return.
        """
        if is_port_open(self.host, self.port):
            return True

        if not self.exe_path.exists():
            return False

        args: list[str] = [str(self.exe_path)]
        if headless:
            args.append("--no-gui")

        # On Windows, DETACHED_PROCESS keeps the child alive past us cleanly
        # and CREATE_NO_WINDOW hides any phantom console.
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )

        # Don't poison the child with our (Python-side) Qt platform overrides.
        # If we inherit QT_QPA_PLATFORM=offscreen (set by tests / headless
        # runs), LibreVNA-GUI dies with "no Qt platform plugin could be
        # initialized" because it only ships the Windows plugin.
        env = os.environ.copy()
        for k in (
            "QT_QPA_PLATFORM", "QT_QPA_PLATFORM_PLUGIN_PATH",
            "QT_PLUGIN_PATH", "QT_AUTO_SCREEN_SCALE_FACTOR",
            "QT_SCALE_FACTOR", "QT_DEBUG_PLUGINS",
        ):
            env.pop(k, None)

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
        except OSError:
            self._proc = None
            return False

        # Poll for the SCPI port to come up.
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if is_port_open(self.host, self.port):
                return True
            if self._proc.poll() is not None:
                return False
            time.sleep(0.25)
        return is_port_open(self.host, self.port)

    def stop(self) -> None:
        """Kill the subprocess only if we started it."""
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
