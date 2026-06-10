"""Top-level window for the radar VNA workbench."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt6.QtCore import QThread, QTimer, pyqtSlot
from PyQt6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .models import BackgroundProfile, CaptureSession, RadarConfig, RadarFrame, SweepConfig, SweepFrame
from .plots import DspInspectorView, RadarView, ReplayView, VnaVerifyView
from .radar_dsp import process_s21
from .storage import (
    BACKGROUND_DIR,
    CAPTURE_DIR,
    load_background,
    load_capture,
    load_settings,
    save_background,
    save_capture,
    save_settings,
)
from .ui_panels import BackgroundPanel, CapturePanel, ConnectionPanel, RadarPanel, SweepPanel
from .vna_worker import VnaWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Radar VNA Workbench")
        self._librevna_launcher = None  # managed auto-launch subprocess
        self.resize(1700, 1000)
        self.settings = load_settings()

        self._worker: Optional[VnaWorker] = None
        self._thread: Optional[QThread] = None
        self._last_frame: Optional[SweepFrame] = None
        self._last_radar: Optional[RadarFrame] = None
        self._ema_state: Optional[np.ndarray] = None
        self._background: Optional[BackgroundProfile] = None
        self._acquire_target = 0
        self._acquire_frames: list[np.ndarray] = []
        self._capture_frames: list[np.ndarray] = []
        self._capture_s11: list[np.ndarray] = []
        self._capture_times: list[float] = []
        self._capture_peak_distance: list[float] = []
        self._capture_peak_amplitude: list[float] = []
        self._recording = False
        self._replay: Optional[CaptureSession] = None

        self._build_ui()
        self._wire()
        self._restore_settings()
        self._librevna_usb_was_present = False
        self._auto_connect_timer = QTimer(self)
        self._auto_connect_timer.setInterval(2000)
        self._auto_connect_timer.timeout.connect(self._check_auto_connect)
        self._auto_connect_timer.start()
        QTimer.singleShot(500, self._check_auto_connect)

    def _build_ui(self) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(6)
        self.connection = ConnectionPanel()
        self.sweep = SweepPanel()
        self.radar_controls = RadarPanel()
        self.background = BackgroundPanel()
        self.capture = CapturePanel()
        for panel in (self.connection, self.sweep, self.radar_controls, self.background, self.capture):
            left_layout.addWidget(panel)
        left_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)

        self.tabs = QTabWidget()
        self.radar_view = RadarView()
        self.vna_view = VnaVerifyView()
        self.inspector = DspInspectorView()
        self.replay_view = ReplayView()
        self.tabs.addTab(self.radar_view, "Radar")
        self.tabs.addTab(self.vna_view, "VNA Verify")
        self.tabs.addTab(self.inspector, "DSP Inspector")
        self.tabs.addTab(self.replay_view, "Replay")

        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 1320])
        self.setCentralWidget(split)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready.")

    def _wire(self) -> None:
        self.connection.connect_requested.connect(self._connect)
        self.connection.disconnect_requested.connect(self._disconnect)
        self.connection.load_cal_requested.connect(self._load_calibration)
        self.connection.conn_type.currentIndexChanged.connect(self._on_conn_type_changed)
        self.sweep.preset_chosen.connect(self._preset_chosen)
        self.radar_controls.config_changed.connect(self._reset_ema)
        self.background.acquire_requested.connect(self._start_background_acquire)
        self.background.save_requested.connect(self._save_background)
        self.background.load_requested.connect(self._load_background)
        self.background.clear_requested.connect(self._clear_background)
        self.capture.start_requested.connect(self._start_capture)
        self.capture.stop_requested.connect(self._stop_capture)
        self.capture.replay_load_requested.connect(self._load_replay)
        self.replay_view.frame_selected.connect(self._show_replay_frame)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _restore_settings(self) -> None:
        sweep = self.settings.get("last_sweep")
        if isinstance(sweep, dict):
            from .models import SweepConfig

            self.sweep.set_config(SweepConfig.from_dict(sweep))
        backend = self.settings.get("backend")
        if backend:
            self.connection.backend.setCurrentText(str(backend))
        port = self.settings.get("port")
        if port:
            self.connection.port.setCurrentText(str(port))
        conn_type = self.settings.get("conn_type", 0)
        self.connection.conn_type.setCurrentIndex(int(conn_type))
        scpi_host = self.settings.get("scpi_host")
        if scpi_host:
            self.connection.scpi_host.setText(str(scpi_host))
        auto_launch = self.settings.get("auto_launch", True)
        self.connection.auto_launch.setChecked(bool(auto_launch))
        # Sync IFBW/power visibility with connection type
        self._on_conn_type_changed()

    def _save_ui_settings(self) -> None:
        self.settings["last_sweep"] = self.sweep.config().to_dict()
        self.settings["backend"] = self.connection.selected_backend()
        self.settings["port"] = self.connection.selected_port()
        self.settings["conn_type"] = self.connection.conn_type.currentIndex()
        self.settings["scpi_host"] = self.connection.scpi_host.text().strip()
        self.settings["auto_launch"] = self.connection.auto_launch.isChecked()
        save_settings(self.settings)

    def _on_conn_type_changed(self) -> None:
        """Toggle LibreVNA-specific UI elements based on connection type."""
        is_tcp = self.connection.is_tcp_mode()
        self.sweep.show_librevna_fields(is_tcp)

    def _check_auto_connect(self) -> None:
        """Periodically check if LibreVNA USB device is plugged in to auto-connect."""
        if not (self.connection.is_tcp_mode() and self.connection.auto_launch.isChecked()):
            return

        from .librevna_backend import is_librevna_usb_connected
        is_plugged = is_librevna_usb_connected()

        if is_plugged and not self._librevna_usb_was_present:
            self._librevna_usb_was_present = True
            if self._worker is None:
                backend_name = self.connection.selected_backend()
                port = self.connection.scpi_host.text().strip()
                self._connect(backend_name, port)
        elif not is_plugged:
            self._librevna_usb_was_present = False

    def _clear_connection_references(self) -> None:
        self._worker = None
        self._thread = None

    def _on_tab_changed(self, index: int) -> None:
        """Update the newly active tab immediately with the latest data."""
        # Defer to allow the tab widget to finish its transition and layout pass
        QTimer.singleShot(50, lambda: self._update_active_tab_deferred(index))

    def _update_active_tab_deferred(self, index: int) -> None:
        if self.tabs.currentIndex() != index:
            return
        widget = self.tabs.widget(index)
        if widget is self.radar_view and self._last_radar is not None:
            self.radar_view.update_radar(self._last_radar, active=True)
        elif widget is self.vna_view and self._last_frame is not None:
            self.vna_view.update_sweep(self._last_frame)
        elif widget is self.inspector and self._last_radar is not None:
            self.inspector.update_inspector(self._last_radar)

    @pyqtSlot(str, str)
    def _connect(self, backend_name: str, port: str) -> None:
        if not port:
            QMessageBox.information(self, "No port/host", "Choose a COM port or enter an SCPI host first.")
            return

        # Auto-launch LibreVNA-GUI if needed
        if self.connection.is_tcp_mode() and self.connection.auto_launch.isChecked():
            from .librevna_backend import LibreVnaScpiBackend, is_port_open
            host, port_num = LibreVnaScpiBackend._parse_endpoint(port)
            
            # Reuse or stop old launcher if host/port changed
            if self._librevna_launcher is not None:
                if self._librevna_launcher.host != host or self._librevna_launcher.port != port_num:
                    try:
                        self._librevna_launcher.stop()
                    except Exception:
                        pass
                    self._librevna_launcher = None

            if not is_port_open(host, port_num):
                self.connection.set_status("Launching LibreVNA-GUI...")
                from .librevna_backend import LibreVnaLauncher
                if self._librevna_launcher is None:
                    self._librevna_launcher = LibreVnaLauncher(host=host, port=port_num)
                if not self._librevna_launcher.ensure_running():
                    self.connection.set_status(
                        "Could not launch LibreVNA-GUI. Start it manually or check the path.",
                        warn=True,
                    )
                    return
                self.connection.set_status("LibreVNA-GUI launched, connecting...")

        self._disconnect()
        self._save_ui_settings()
        self._reset_ema()
        worker = VnaWorker(backend_name, port, self.sweep.config())
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.frame_received.connect(self._on_frame)
        worker.connected.connect(self._on_worker_connected)
        worker.status.connect(lambda msg: self.connection.set_status(msg))
        worker.error.connect(self._on_worker_error)
        
        worker.stopped.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_connection_references)
        
        thread.started.connect(worker.run)
        self._worker = worker
        self._thread = thread
        self.connection.set_status("starting worker...")
        thread.start()

    def _disconnect(self) -> None:
        worker = self._worker
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass

        thread = self._thread
        if thread is not None:
            try:
                thread.quit()
                finished = thread.wait(2000)
                if not finished:
                    print("[WARNING] QThread did not finish within 2000ms", flush=True)
            except RuntimeError:
                pass
        
        if thread is None or thread.isFinished():
            self._worker = None
            self._thread = None
        self.connection.set_connected(False)

    @pyqtSlot(str)
    def _on_worker_connected(self, info: str) -> None:
        self.connection.set_connected(True, info)
        self.statusBar().showMessage(f"Connected: {info}", 5000)

    @pyqtSlot(str)
    def _on_worker_error(self, message: str) -> None:
        self.connection.set_status(message, warn=True)
        self.statusBar().showMessage(f"VNA error: {message}", 8000)

    @pyqtSlot(object)
    def _on_frame(self, frame: SweepFrame) -> None:
        self.connection.clear_error_status()
        self._last_frame = frame
        if self._acquire_target:
            self._acquire_frames.append(np.array(frame.s21, copy=True))
            self.statusBar().showMessage(
                f"Acquiring background {len(self._acquire_frames)} / {self._acquire_target}",
                1000,
            )
            if len(self._acquire_frames) >= self._acquire_target:
                self._finish_background_acquire(frame)
        radar_frame = self._process_and_update(frame)
        if self._recording and radar_frame is not None:
            self._capture_frames.append(np.array(frame.s21, copy=True))
            if frame.s11 is not None:
                self._capture_s11.append(np.array(frame.s11, copy=True))
            self._capture_times.append(float(frame.timestamp))
            if radar_frame.peaks:
                self._capture_peak_distance.append(float(radar_frame.peaks[0].distance_m))
                self._capture_peak_amplitude.append(float(radar_frame.peaks[0].amplitude))
            else:
                self._capture_peak_distance.append(float("nan"))
                self._capture_peak_amplitude.append(float("nan"))
            self.capture.set_recording(True, len(self._capture_frames))

    def _process_and_update(
        self,
        frame: SweepFrame,
        sweep_config: Optional[SweepConfig] = None,
        radar_config: Optional[RadarConfig] = None,
    ) -> Optional[RadarFrame]:
        sweep_config = sweep_config or self.sweep.config()
        radar_config = radar_config or self.radar_controls.config(self._background.name if self._background else "")
        bg = self._background.complex_s21_avg if self._background is not None else None
        if bg is not None and bg.shape != frame.s21.shape:
            bg = None
            self.statusBar().showMessage("Loaded background shape does not match current sweep.", 4000)
        try:
            radar_frame, self._ema_state = process_s21(
                frame.s21,
                sweep_config,
                radar_config,
                background=bg,
                previous_ema=self._ema_state,
                include_intermediates=True,
            )
        except Exception as exc:
            self.statusBar().showMessage(f"DSP error: {exc}", 8000)
            return None
        self._last_radar = radar_frame
        
        # Always update radar_view to collect background waterfall history,
        # but only render if it is the active/visible tab.
        active_widget = self.tabs.currentWidget()
        self.radar_view.update_radar(radar_frame, active=(active_widget is self.radar_view))
        
        if active_widget is self.vna_view:
            self.vna_view.update_sweep(frame)
        elif active_widget is self.inspector:
            self.inspector.update_inspector(radar_frame)
            
        return radar_frame

    def _preset_chosen(self, name: str) -> None:
        if name == "Close Range":
            self.radar_controls.range_max.setValue(3.0)
            self.radar_controls.ascope_bins.setValue(4096)
        elif name == "Max Distance":
            self.radar_controls.range_max.setValue(25.0)
            self.radar_controls.ascope_bins.setValue(4096)
        else:
            self.radar_controls.range_max.setValue(10.0)
            self.radar_controls.ascope_bins.setValue(2048)
        self._reset_ema()
        self.statusBar().showMessage(f"Preset applied: {name}. Reconnect to push sweep changes.", 5000)

    def _reset_ema(self) -> None:
        self._ema_state = None
        self.radar_view.clear_history()

    @pyqtSlot(int)
    def _start_background_acquire(self, sweeps: int) -> None:
        if self._last_frame is None and self._worker is None:
            QMessageBox.information(self, "Not connected", "Connect and start receiving sweeps first.")
            return
        self._acquire_target = int(sweeps)
        self._acquire_frames = []
        self.statusBar().showMessage("Background acquisition armed.", 3000)

    def _finish_background_acquire(self, frame: SweepFrame) -> None:
        avg = np.mean(np.vstack(self._acquire_frames), axis=0)
        self._background = BackgroundProfile(
            name="Unsaved background",
            sweep_config=self.sweep.config(),
            complex_s21_avg=avg,
            created_at=time.time(),
            device_id=frame.device_id,
        )
        self._acquire_target = 0
        self._acquire_frames = []
        self.background.set_name(self._background.name)
        self.inspector.set_background(avg)
        self._reset_ema()
        self.statusBar().showMessage("Background acquired.", 5000)

    def _save_background(self) -> None:
        if self._background is None:
            QMessageBox.information(self, "No background", "Acquire or load a background first.")
            return
        name, ok = QInputDialog.getText(self, "Save background", "Background name:", text=self._background.name)
        if not ok or not name.strip():
            return
        self._background.name = name.strip()
        path = save_background(self._background)
        self.background.set_name(self._background.name)
        self.statusBar().showMessage(f"Saved background: {path}", 6000)

    def _load_background(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load background",
            str(BACKGROUND_DIR),
            "Radar backgrounds (*.npz)",
        )
        if not path:
            return
        try:
            self._background = load_background(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
            return
        self.background.set_name(self._background.name)
        self.inspector.set_background(self._background.complex_s21_avg)
        self._reset_ema()
        self.statusBar().showMessage(f"Loaded background: {path}", 6000)

    def _clear_background(self) -> None:
        self._background = None
        self.background.set_name("")
        self.inspector.set_background(None)
        self._reset_ema()

    def _start_capture(self) -> None:
        if self._last_frame is None:
            QMessageBox.information(self, "No sweeps yet", "Connect and receive at least one sweep first.")
            return
        self._capture_frames = []
        self._capture_s11 = []
        self._capture_times = []
        self._capture_peak_distance = []
        self._capture_peak_amplitude = []
        self._recording = True
        self.capture.set_recording(True, 0)

    def _stop_capture(self) -> None:
        self._recording = False
        self.capture.set_recording(False)
        if not self._capture_frames or self._last_frame is None:
            return
        name, ok = QInputDialog.getText(
            self,
            "Save capture",
            "Capture name:",
            text=f"radar_capture_{time.strftime('%Y%m%d_%H%M%S')}",
        )
        if not ok or not name.strip():
            return
        s21_frames = np.vstack([f[None, :] for f in self._capture_frames])
        s11_frames = None
        if len(self._capture_s11) == len(self._capture_frames):
            s11_frames = np.vstack([f[None, :] for f in self._capture_s11])
        session = CaptureSession(
            name=name.strip(),
            sweep_config=self.sweep.config(),
            radar_config=self.radar_controls.config(self._background.name if self._background else ""),
            timestamps=np.asarray(self._capture_times, dtype=float),
            freq_hz=np.asarray(self._last_frame.freq_hz, dtype=float),
            s21_frames=s21_frames,
            s11_frames=s11_frames,
            peak_distance_m=np.asarray(self._capture_peak_distance, dtype=float),
            peak_amplitude=np.asarray(self._capture_peak_amplitude, dtype=float),
            background_name=self._background.name if self._background else "",
            device_id=self._last_frame.device_id,
        )
        path = save_capture(session)
        self.statusBar().showMessage(f"Saved capture: {path}", 7000)

    def _load_replay(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load replay capture",
            str(CAPTURE_DIR),
            "Radar captures (*.npz)",
        )
        if not path:
            return
        try:
            self._replay = load_capture(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
            return
        self.replay_view.set_count(self._replay.frame_count())
        self.replay_view.list.clear()
        self.replay_view.list.addItem(f"Capture: {self._replay.name}")
        self.replay_view.list.addItem(f"Frames: {self._replay.frame_count()}")
        self.replay_view.list.addItem(f"Background: {self._replay.background_name or 'none'}")
        self.tabs.setCurrentWidget(self.replay_view)
        self._show_replay_frame(0)

    @pyqtSlot(int)
    def _show_replay_frame(self, idx: int) -> None:
        if self._replay is None or idx < 0 or idx >= self._replay.frame_count():
            return
        s11 = self._replay.s11_frames[idx] if self._replay.s11_frames is not None else None
        frame = SweepFrame(
            freq_hz=self._replay.freq_hz,
            s11=s11,
            s21=self._replay.s21_frames[idx],
            timestamp=float(self._replay.timestamps[idx]),
            device_id=self._replay.device_id,
            raw_meta={"replay": self._replay.name},
        )
        old_ema = self._ema_state
        self._ema_state = None
        self._process_and_update(frame, self._replay.sweep_config, self._replay.radar_config)
        self._ema_state = old_ema

    def _load_calibration(self) -> None:
        """Load a .cal file onto the connected LibreVNA device."""
        from .librevna_backend import LibreVnaScpiBackend
        # Find the vna_gui/cals directory for default location
        from .storage import PROJECT_DIR
        cals_dir = str(PROJECT_DIR / "vna_gui" / "cals")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load calibration file",
            cals_dir,
            "Calibration files (*.cal);;All files (*)",
        )
        if not path:
            return
        if not self.connection.is_tcp_mode():
            QMessageBox.information(self, "Not supported", "Calibration loading is only available for LibreVNA.")
            return

        was_connected = (self._worker is not None)
        if was_connected:
            self._disconnect()

        endpoint = self.connection.scpi_host.text().strip()
        backend = LibreVnaScpiBackend()
        ok = False
        cal_name = ""
        try:
            backend.connect(endpoint)
            ok = backend.load_calibration(path)
            cal_name = backend.active_calibration()
            backend.disconnect()
        except Exception as exc:
            QMessageBox.warning(self, "Calibration error", str(exc))

        if ok:
            msg = f"Calibration loaded: {Path(path).name}"
            if cal_name:
                msg += f" (active: {cal_name})"
            self.statusBar().showMessage(msg, 8000)
            self.connection.set_status(msg)
        else:
            self.connection.set_status(f"Failed to load calibration: {Path(path).name}", warn=True)

        if was_connected:
            backend_name = self.connection.selected_backend()
            self._connect(backend_name, endpoint)

    def closeEvent(self, event) -> None:
        self._save_ui_settings()
        self._disconnect()
        # Stop any auto-launched LibreVNA-GUI subprocess
        if self._librevna_launcher is not None:
            self._librevna_launcher.stop()
            self._librevna_launcher = None
        super().closeEvent(event)
