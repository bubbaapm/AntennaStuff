"""
VNA Tester main window.

Top-level QMainWindow that orchestrates:
  • portable path discovery + LibreVNA-GUI auto-launch
  • SCPI controller + sweep worker thread
  • trace manager fed by the worker
  • plot grid (tile-able panels)
  • side panels: connection / sweep / traces / markers / metrics / presets
  • menus for file (s2p save/load, image export, session, presets)
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox,
    QSplitter, QStatusBar, QTabWidget, QToolBar, QVBoxLayout, QWidget, QHBoxLayout,
    QScrollArea, QPushButton, QLabel,
)

from ..controller import VnaController, SweepConfig
from ..launcher import LibreVnaLauncher, is_port_open
from ..paths import (
    find_librevna_gui, load_config, save_config, remember_librevna_path,
    app_root,
)
from ..plots.export import export_grid_composite, export_panel, export_widget_screenshot
from ..plots.grid import PlotGrid
from ..trace import TraceAssignment, TraceManager, VNA_PARAMS
from ..worker import SweepWorker

from .band_presets import BandPresets, BUILTIN_PRESETS
from .calibration_dialog import CalibrationDialog
from .connection_panel import ConnectionPanel
from .export_dialog import ExportDialog
from .marker_panel import MarkerPanel
from .metrics_panel import MetricsPanel
from .plot_config_dialog import ConfigurePlotDialog
from .sweep_panel import SweepPanel
from .trace_panel import TracePanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VNA Tester — antenna measurement (LibreVNA)")
        self.resize(1700, 1000)

        self.cfg = load_config()
        self._librevna_path = find_librevna_gui(self.cfg.get("librevna_path"))
        if self._librevna_path:
            remember_librevna_path(self._librevna_path)

        self.traces = TraceManager()
        self.controller = VnaController(
            host=self.cfg.get("scpi_host", "localhost"),
            port=int(self.cfg.get("scpi_port", 19542)),
        )
        self.controller.connected_changed.connect(self._on_connected_changed)
        self.controller.error.connect(self._on_error)
        self.controller.info_message.connect(self._on_info)

        self.launcher = LibreVnaLauncher(
            self._librevna_path or Path("LibreVNA-GUI.exe"),
            host=self.cfg.get("scpi_host", "localhost"),
            port=int(self.cfg.get("scpi_port", 19542)),
        )

        self._sweep_worker: Optional[SweepWorker] = None
        self._sweep_thread: Optional[QThread] = None
        self._csv_log_file: Optional[object] = None
        self._csv_log_writer: Optional[csv.writer] = None
        self._device_status_timer = QTimer(self)
        self._device_status_timer.setInterval(5000)
        self._device_status_timer.timeout.connect(self._refresh_device_status)

        self._build_ui()
        self._build_menu()
        self._wire()

        # Session: restore custom presets if any
        custom = self.cfg.get("saved_band_presets", {})
        if custom:
            self.presets.restore_custom(custom)

        # Tooltip on title bar
        self.statusBar().showMessage(
            f"Ready. LibreVNA-GUI: {self._librevna_path or 'NOT FOUND — use Browse'}", 8000
        )

    # ------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        # --- left side panels (in a scroll area for small screens)
        host_left = QWidget()
        ll = QVBoxLayout(host_left)
        ll.setContentsMargins(6, 6, 6, 6)
        ll.setSpacing(6)

        self.conn = ConnectionPanel(
            host=self.cfg.get("scpi_host", "localhost"),
            port=int(self.cfg.get("scpi_port", 19542)),
            librevna_path=str(self._librevna_path or ""),
        )
        ll.addWidget(self.conn)

        self.sweep_panel = SweepPanel()
        ll.addWidget(self.sweep_panel)

        self.presets = BandPresets()
        ll.addWidget(self.presets)
        ll.addStretch(1)

        scroll_left = QScrollArea()
        scroll_left.setWidget(host_left)
        scroll_left.setWidgetResizable(True)
        scroll_left.setFrameShape(QScrollArea.Shape.NoFrame)
        # Min width that's wide enough for the natural sizeHint of the
        # widest panel (Connection ≈ 328) so an h-scrollbar never shows
        # at default — the user can still drag it narrower if they want.
        scroll_left.setMinimumWidth(330)
        scroll_left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # --- center: tile-able plot grid
        self.plot_grid = PlotGrid(self.traces)

        # --- right: traces / markers / metrics
        host_right = QWidget()
        rl = QVBoxLayout(host_right)
        rl.setContentsMargins(6, 6, 6, 6)
        rl.setSpacing(6)
        self.trace_panel = TracePanel(self.traces)
        rl.addWidget(self.trace_panel)
        self.marker_panel = MarkerPanel(self.traces)
        rl.addWidget(self.marker_panel)
        self.metrics_panel = MetricsPanel(self.traces)
        rl.addWidget(self.metrics_panel)
        rl.addStretch(1)

        scroll_right = QScrollArea()
        scroll_right.setWidget(host_right)
        scroll_right.setWidgetResizable(True)
        scroll_right.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_right.setMinimumWidth(290)
        scroll_right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # No vertical scrollbar override — vertical scrolling is fine.

        # --- splitter
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(scroll_left)
        split.addWidget(self.plot_grid)
        split.addWidget(scroll_right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([340, 1060, 320])
        self.setCentralWidget(split)

        self.setStatusBar(QStatusBar())

    def _build_menu(self) -> None:
        mb = self.menuBar()

        f = mb.addMenu("&File")
        a_save_s2p = QAction("Save current as .s2p…", self)
        a_save_s2p.setShortcut(QKeySequence("Ctrl+S"))
        a_save_s2p.triggered.connect(self._save_s2p)
        f.addAction(a_save_s2p)

        a_save_s1p = QAction("Save current as .s1p…", self)
        a_save_s1p.triggered.connect(self._save_s1p)
        f.addAction(a_save_s1p)

        a_load_ref = QAction("Load Touchstone (.s1p / .s2p)…", self)
        a_load_ref.triggered.connect(self.trace_panel._load_reference)
        f.addAction(a_load_ref)

        f.addSeparator()
        a_export = QAction("Export image…", self)
        a_export.setShortcut(QKeySequence("Ctrl+E"))
        a_export.triggered.connect(self._export_image)
        f.addAction(a_export)

        f.addSeparator()
        a_save_session = QAction("Save session…", self)
        a_save_session.triggered.connect(self._save_session)
        f.addAction(a_save_session)
        a_load_session = QAction("Load session…", self)
        a_load_session.triggered.connect(self._load_session)
        f.addAction(a_load_session)

        f.addSeparator()
        a_csv_start = QAction("Start CSV log…", self)
        a_csv_start.triggered.connect(self._start_csv_log)
        f.addAction(a_csv_start)
        a_csv_stop = QAction("Stop CSV log", self)
        a_csv_stop.triggered.connect(self._stop_csv_log)
        f.addAction(a_csv_stop)

        f.addSeparator()
        a_save_preset = QAction("Save current sweep as preset…", self)
        a_save_preset.triggered.connect(self._save_current_as_preset)
        f.addAction(a_save_preset)

        f.addSeparator()
        a_quit = QAction("Quit", self)
        a_quit.setShortcut(QKeySequence.StandardKey.Quit)
        a_quit.triggered.connect(self.close)
        f.addAction(a_quit)

        v = mb.addMenu("&VNA")
        a_apply_sweep = QAction("Apply sweep settings", self)
        a_apply_sweep.setShortcut("F5")
        a_apply_sweep.triggered.connect(self._apply_sweep_clicked)
        v.addAction(a_apply_sweep)

        a_run = QAction("Run", self)
        a_run.triggered.connect(self._run)
        v.addAction(a_run)

        a_stop = QAction("Stop", self)
        a_stop.triggered.connect(self._stop)
        v.addAction(a_stop)

        a_single = QAction("Single sweep", self)
        a_single.setShortcut("F6")
        a_single.triggered.connect(self._single)
        v.addAction(a_single)

        v.addSeparator()
        a_cal = QAction("Calibration wizard…", self)
        a_cal.setShortcut("F8")
        a_cal.triggered.connect(self._open_cal)
        v.addAction(a_cal)

        h = mb.addMenu("&Help")
        a_about = QAction("About", self)
        a_about.triggered.connect(self._about)
        h.addAction(a_about)

    def _wire(self) -> None:
        # Connection
        self.conn.connect_requested.connect(self._do_connect)
        self.conn.disconnect_requested.connect(self._do_disconnect)
        self.conn.refresh_devices.connect(self._refresh_device_list)
        self.conn.device_chosen.connect(self._use_device)
        self.conn.browse_librevna.connect(self._set_librevna_path)

        # Sweep
        self.sweep_panel.sweep_changed.connect(self._on_sweep_changed)
        self.sweep_panel.run_requested.connect(self._run)
        self.sweep_panel.stop_requested.connect(self._stop)
        self.sweep_panel.single_requested.connect(self._single)

        # Traces
        self.trace_panel.save_s2p_requested.connect(self._save_s2p)
        self.trace_panel.save_s1p_requested.connect(self._save_s1p)
        self.trace_panel.references_loaded.connect(self._on_references_loaded)
        self.trace_panel.references_cleared.connect(self._on_references_cleared)

        # Plot grid → markers
        self.plot_grid.marker_placed.connect(self._on_plot_clicked)
        self.plot_grid.marker_dragged.connect(self.marker_panel.marker_drag.emit)
        self.plot_grid.marker_context.connect(self._on_marker_context)
        self.plot_grid.panel_configure.connect(self._open_plot_config)
        self.plot_grid.export_all_requested.connect(self._export_image_window)

        # Marker panel → plots
        self.marker_panel.markers_changed.connect(self.plot_grid.set_markers)
        # Marker target dB drives both BW markers AND the verdict in metrics
        self.marker_panel.target_db_changed.connect(self.metrics_panel.set_target_db)

        # Presets
        self.presets.preset_chosen.connect(self._apply_preset)

    # ====================================================== connection ==
    def _do_connect(self, host: str, port: int, auto_launch: bool) -> None:
        self.cfg["scpi_host"] = host
        self.cfg["scpi_port"] = int(port)
        save_config(self.cfg)
        self.controller.set_endpoint(host, port)
        self.launcher = LibreVnaLauncher(
            self._librevna_path or Path("LibreVNA-GUI.exe"),
            host=host, port=port,
        )

        if not is_port_open(host, port):
            self.conn.set_status("warn", "starting LibreVNA-GUI…")
            QApplication.processEvents()
            ok = self.launcher.ensure_running(wait_seconds=10.0, headless=True)
            if not ok:
                self.conn.set_status("err", "couldn't auto-launch LibreVNA-GUI")
                QMessageBox.warning(
                    self, "Launch failed",
                    "Couldn't reach the SCPI server.\n\n"
                    "Make sure LibreVNA-GUI.exe is installed; use Browse to set its path,\n"
                    "or open LibreVNA-GUI manually first."
                )
                return

        if not self.controller.connect_to_server():
            return
        cur = self.controller.connected_serial()
        if not cur or cur.lower() == "not connected":
            self.controller.connect_device("")
        # Make sure live traces exist on the device
        self.controller.ensure_default_traces()
        self._refresh_device_list()
        # Pull sweep config back from the device so the UI reflects truth
        cfg = self.controller.read_sweep_config()
        if cfg.points > 0:
            self.sweep_panel.write_config(cfg)
        self._start_sweep_worker()

    def _do_disconnect(self) -> None:
        self._stop_sweep_worker()
        self.controller.disconnect()

    @pyqtSlot(bool)
    def _on_connected_changed(self, ok: bool) -> None:
        if ok:
            idn = self.controller.idn() or "(connected)"
            self.conn.set_connected(True, idn[:60])
            self._device_status_timer.start()
            self._refresh_device_status()
        else:
            self.conn.set_connected(False)
            self.conn.set_temperatures("", {})
            self._device_status_timer.stop()
        self.statusBar().showMessage("Connected." if ok else "Disconnected.", 4000)

    def _refresh_device_status(self) -> None:
        if not self.controller.connected:
            return
        temps = self.controller.device_temperatures()
        flags = self.controller.device_status_flags()
        self.conn.set_temperatures(temps, flags)

    def _refresh_device_list(self) -> None:
        if not self.controller.connected:
            return
        serials = self.controller.list_devices()
        cur = self.controller.connected_serial()
        self.conn.set_device_list(serials, selected=cur)

    def _use_device(self, serial: str) -> None:
        if not self.controller.connected:
            return
        self.controller.connect_device(serial or "")
        self.statusBar().showMessage(
            f"Asked LibreVNA-GUI to use device: {serial or '(any)'}", 4000
        )

    def _set_librevna_path(self, path: str) -> None:
        if not path:
            return
        p = Path(path)
        self._librevna_path = p
        self.cfg["librevna_path"] = str(p)
        save_config(self.cfg)
        remember_librevna_path(p)
        self.launcher = LibreVnaLauncher(
            p, host=self.cfg.get("scpi_host", "localhost"),
            port=int(self.cfg.get("scpi_port", 19542)),
        )
        self.conn.set_librevna_path(str(p))

    # ========================================================== sweep ==
    def _on_sweep_changed(self, cfg: SweepConfig) -> None:
        # Always clamp X to the sweep range, even when no VNA is connected.
        # Otherwise loaded references (which usually span a wider band) keep
        # the plot zoomed out to their full range while the live trace only
        # covers the new sweep — exactly the "weird zoomed-out look" we want
        # to avoid.
        self._reset_all_plot_views(sweep_x_range=(cfg.start_hz, cfg.stop_hz))
        if not self.controller.connected:
            return
        self.controller.apply_sweep(cfg)
        self.cfg["last_sweep"] = cfg.__dict__
        save_config(self.cfg)
        self.statusBar().showMessage(
            f"Applied: {cfg.start_hz/1e6:.2f}–{cfg.stop_hz/1e6:.2f} MHz · "
            f"{cfg.points} pts · IFBW {cfg.ifbw_hz:g} Hz · avg {cfg.averaging}",
            5000,
        )

    def _reset_all_plot_views(self, sweep_x_range: Optional[tuple] = None) -> None:
        for p in self.plot_grid.panels():
            try:
                # Only cartesian plots use frequency on the X axis. For Smith
                # / polar / TDR a sweep-range clamp is meaningless, so we just
                # autorange them. For cartesian, we clamp X to the sweep range
                # (and autorange Y) so loaded references don't expand the
                # view past the active band.
                if sweep_x_range is not None and getattr(p, "KIND", "") == "cartesian":
                    lo, hi = sweep_x_range
                    # Invalidate the cached applied state so set_axis_ranges
                    # actually pushes through to pyqtgraph even if Y was
                    # already in autorange mode.
                    if hasattr(p, "_applied_axes"):
                        p._applied_axes = {"x": (None, None, None),
                                           "yl": (None, None, None),
                                           "yr": (None, None, None)}
                    p.set_axis_ranges(
                        x_auto=False, x_min=float(lo), x_max=float(hi),
                        yl_auto=True, yl_min=p.yl_min, yl_max=p.yl_max,
                        yr_auto=True, yr_min=p.yr_min, yr_max=p.yr_max,
                    )
                else:
                    p.reset_view()
            except Exception:
                pass

    def _apply_sweep_clicked(self) -> None:
        self._on_sweep_changed(self.sweep_panel.read_config())

    def _run(self) -> None:
        if not self.controller.connected:
            return
        self.controller.set_single(False)
        self.controller.set_run(True)
        self.statusBar().showMessage("Running…", 3000)

    def _stop(self) -> None:
        if not self.controller.connected:
            return
        self.controller.set_run(False)
        self.statusBar().showMessage("Stopped.", 3000)

    def _single(self) -> None:
        if not self.controller.connected:
            return
        self.controller.set_single(True)
        self.controller.set_run(True)
        self.statusBar().showMessage("Single sweep…", 3000)

    # ----------------------------------------------------------- worker
    def _start_sweep_worker(self) -> None:
        if self._sweep_worker is not None:
            return
        # Share the controller's SCPI client — its internal lock makes it
        # safe across threads, and it dodges any single-client limit on
        # LibreVNA-GUI's SCPI server.
        worker = SweepWorker(self.controller.client, list(VNA_PARAMS),
                             poll_interval_s=0.4)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.traces_batch.connect(self._on_traces_batch)
        worker.progress.connect(self.sweep_panel.set_progress)
        worker.error.connect(lambda m: self.statusBar().showMessage(f"sweep: {m}", 6000))
        worker.stopped.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.start()
        self._sweep_worker = worker
        self._sweep_thread = thread

    def _stop_sweep_worker(self) -> None:
        if self._sweep_worker is not None:
            self._sweep_worker.stop()
        if self._sweep_thread is not None:
            self._sweep_thread.quit()
            self._sweep_thread.wait(1500)
        self._sweep_worker = None
        self._sweep_thread = None

    @pyqtSlot(dict)
    def _on_traces_batch(self, batch: dict) -> None:
        # Single atomic update — TraceManager emits exactly one traces_data
        # signal regardless of how many parameters changed.
        if not batch:
            return
        self.traces.bulk_update(batch)
        if self._csv_log_writer is not None and "S11" in batch:
            try:
                from ..metrics import antenna_metrics
                t = self.traces.get("S11")
                if t is not None:
                    import time as _t
                    m = antenna_metrics(t)
                    self._csv_log_writer.writerow([
                        f"{_t.time():.3f}", m.f_resonance_hz,
                        m.s11_min_db, m.vswr_at_resonance,
                        m.bandwidth_m10db_hz, m.fractional_bw_pct,
                        m.impedance_at_resonance.real, m.impedance_at_resonance.imag,
                        m.quality_factor,
                    ])
                    if self._csv_log_file is not None:
                        self._csv_log_file.flush()
            except Exception:
                pass

    # ====================================================== plot input ==
    def _on_plot_clicked(self, trace_name: str, freq_hz: float,
                         panel_id: str = "") -> None:
        # Click-placed markers default to panel scope (only the plot that
        # was clicked). User can right-click to broaden to all plots.
        self.marker_panel.add_normal_at_freq.emit(trace_name, freq_hz, panel_id)

    # ========================================================== files ==
    def _save_s2p(self) -> None:
        self._save_touchstone(default_name="antenna.s2p", port_count=2)

    def _save_s1p(self) -> None:
        # Ask which port to export — S11 (port 1 reflection) or S22 (port 2).
        choice, ok = QInputDialog.getItem(
            self, "Save .s1p — choose port",
            "Which port's reflection do you want to export?",
            ["Port 1 (S11)", "Port 2 (S22)"], 0, False,
        )
        if not ok:
            return
        param = "S22" if choice.startswith("Port 2") else "S11"
        default_name = f"antenna_{param.lower()}.s1p"
        self._save_touchstone(default_name=default_name, port_count=1, s1p_param=param)

    def _save_touchstone(self, default_name: str, port_count: int,
                         s1p_param: str = "S11") -> None:
        if not self.controller.connected:
            QMessageBox.information(self, "Not connected", "Connect to the VNA first.")
            return
        flt = (
            "Touchstone S1P (*.s1p);;Touchstone S2P (*.s2p)" if port_count == 1
            else "Touchstone S2P (*.s2p);;Touchstone S1P (*.s1p)"
        )
        fn, _ = QFileDialog.getSaveFileName(self, "Save Touchstone", default_name, flt)
        if not fn:
            return
        single = port_count == 1 or fn.lower().endswith(".s1p")
        names = [s1p_param] if single else ["S11", "S21", "S12", "S22"]
        data = self.controller.get_touchstone(names)
        if not data.strip():
            QMessageBox.warning(self, "Save failed",
                                "Device returned no Touchstone data — is a sweep complete?")
            return
        try:
            Path(fn).write_text(data, encoding="utf-8")
            self.statusBar().showMessage(f"Saved: {fn}", 5000)
        except OSError as e:
            QMessageBox.warning(self, "Save failed", str(e))

    # ---------------------------------------------------- plot configure
    def _open_plot_config(self, panel) -> None:
        names = [t.name for t in self.traces.all()]
        axis_state = {
            "x_auto": panel.x_auto, "x_min": panel.x_min, "x_max": panel.x_max,
            "yl_auto": panel.yl_auto, "yl_min": panel.yl_min, "yl_max": panel.yl_max,
            "yr_auto": panel.yr_auto, "yr_min": panel.yr_min, "yr_max": panel.yr_max,
        }
        dlg = ConfigurePlotDialog(
            plot_kind=panel.KIND,
            title=panel.title,
            assignments=panel.get_assignments(),
            axis_state=axis_state,
            traces=self.traces,
            available_trace_names=names,
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        r = dlg.result_payload()
        panel.set_title(r["title"])
        panel.set_assignments(r["assignments"])
        panel.set_axis_ranges(
            r["x_auto"], r["x_min"], r["x_max"],
            r["yl_auto"], r["yl_min"], r["yl_max"],
            r["yr_auto"], r["yr_min"], r["yr_max"],
        )

    # ----------------------------------------- references → plot assignments
    def _on_references_loaded(self, names: list) -> None:
        """
        After the user loads a .s1p/.s2p, drop the new reference trace into
        every plot panel that already shows a trace with the same S-parameter.
        Mirrors the existing assignment's axis/format so the reference is
        directly comparable, and renders dashed to distinguish it from the
        live trace.
        """
        if not names:
            return
        new_traces = [(n, self.traces.get(n)) for n in names]
        new_traces = [(n, t) for n, t in new_traces if t is not None]
        if not new_traces:
            return
        added_to: list[str] = []
        for panel in self.plot_grid.panels():
            assigns = panel.get_assignments()
            # Map parameter → first matching assignment, so we can reuse
            # axis/y_format when adding the reference. Falling back to
            # `trace_name` covers the no-VNA-connected case: the default
            # plots ship with assignments named "S11"/"S22" that don't
            # resolve to a live Trace yet — but the assignment name itself
            # tells us which S-parameter the panel wants to show.
            template_for: dict[str, TraceAssignment] = {}
            for a in assigns:
                t = self.traces.get(a.trace_name)
                if t is not None:
                    param = t.parameter
                elif a.trace_name in VNA_PARAMS:
                    param = a.trace_name
                else:
                    continue
                if param in template_for:
                    continue
                template_for[param] = a
            if not template_for:
                continue
            new_assigns = list(assigns)
            for ref_name, ref_t in new_traces:
                tmpl = template_for.get(ref_t.parameter)
                if tmpl is None:
                    continue
                new_assigns.append(TraceAssignment(
                    trace_name=ref_name,
                    visible=True,
                    axis=tmpl.axis,
                    y_format=tmpl.y_format,
                    color_override="",     # inherit reference's gray
                    line_style="dash",     # visually distinct from live
                    line_width=tmpl.line_width,
                    show_dots=False,
                ))
            if len(new_assigns) != len(assigns):
                panel.set_assignments(new_assigns)
                added_to.append(panel.header_title)
        if added_to:
            self.statusBar().showMessage(
                f"Added reference trace(s) to: {', '.join(added_to)}", 5000
            )

    def _on_references_cleared(self, names: list) -> None:
        """User cleared all reference traces — prune any plot assignments
        and markers that pointed at them so the UI doesn't carry orphan
        rows around. Live traces and their markers are untouched."""
        if not names:
            return
        dropped = set(names)
        # Strip dropped names from each panel's assignment list.
        for panel in self.plot_grid.panels():
            assigns = panel.get_assignments()
            keep = [a for a in assigns if a.trace_name not in dropped]
            if len(keep) != len(assigns):
                panel.set_assignments(keep)
        # Drop primary-on-ref markers entirely; strip dropped names from
        # the extras list of any other markers.
        markers = self.marker_panel.markers()
        survivors = []
        changed = False
        for m in markers:
            if m.trace_name in dropped:
                changed = True
                continue
            new_extras = [n for n in m.extra_traces if n not in dropped]
            if len(new_extras) != len(m.extra_traces):
                m.extra_traces = new_extras
                changed = True
            survivors.append(m)
        if changed:
            self.marker_panel._markers = survivors
            self.marker_panel._refresh()
        self.statusBar().showMessage(
            f"Removed {len(dropped)} reference trace(s) and cleared their plot/marker overlays.",
            5000,
        )

    # ----------------------------------------------------- marker context
    def _on_marker_context(self, label: str, screen_pos, panel) -> None:
        # Surface the marker panel's menu, scoped to the panel that emitted.
        pid = getattr(panel, "plot_id", "")
        self.marker_panel.show_marker_menu(label, screen_pos, panel_id=pid)

    def _export_image_window(self) -> None:
        """Shortcut: open the export dialog already pointed at 'whole window'."""
        self._export_image(prefer="window")

    def _export_image(self, prefer: str = "") -> None:
        panel_titles = [f"{i+1}. {p.TITLE}" for i, p in enumerate(self.plot_grid.panels())]
        dlg = ExportDialog(panel_titles,
                           default_dir=self.cfg.get("default_export_dir", ""),
                           parent=self)
        if prefer == "window":
            dlg.rb_window.setChecked(True)
        elif prefer == "panel":
            dlg.rb_panel.setChecked(True)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        sel = dlg.selection()
        path = sel["path"]
        size = sel["size"]
        fmt = sel["fmt"]
        ok = False
        if sel["what"] == "panel":
            idx = panel_titles.index(sel["panel"]) if sel["panel"] in panel_titles else 0
            panels = self.plot_grid.panels()
            if 0 <= idx < len(panels):
                ok = export_panel(panels[idx], path, size=size, fmt=fmt)
        elif sel["what"] == "window":
            ok = export_grid_composite(
                self.plot_grid.panels(), path, target_size=size,
                title=self.windowTitle(), fmt=fmt,
            )
        else:  # screenshot
            # Honor the chosen resolution by upscaling the grab to match it.
            # This is a bitmap upscale (not a re-render) so it won't be as
            # crisp as 'whole window', but it does fulfill the user's
            # expectation that selecting 4K produces a 4K-sized file.
            ok = export_widget_screenshot(self, path, target_size=size, fmt=fmt)
        msg = f"Exported: {path}" if ok else f"Failed to export: {path}"
        self.statusBar().showMessage(msg, 6000)
        if ok:
            self.cfg["default_export_dir"] = str(Path(path).parent)
            self.cfg["export_resolution"] = list(size)
            save_config(self.cfg)

    # ================================================== session save/load
    def _save_session(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(
            self, "Save session", "session.json", "Session JSON (*.json)"
        )
        if not fn:
            return
        cfg = self.sweep_panel.read_config()
        data = {
            "sweep": cfg.__dict__,
            "plots": self.plot_grid.to_dict(),
            "custom_presets": self.presets.custom_presets(),
        }
        Path(fn).write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.statusBar().showMessage(f"Saved session: {fn}", 5000)

    def _load_session(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(
            self, "Load session", "", "Session JSON (*.json)"
        )
        if not fn:
            return
        try:
            data = json.loads(Path(fn).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.warning(self, "Load failed", str(e))
            return
        if "sweep" in data:
            self.sweep_panel.write_config(SweepConfig(**data["sweep"]))
        if "plots" in data:
            self.plot_grid.restore(data["plots"])
        if "custom_presets" in data:
            self.presets.restore_custom(data["custom_presets"])
        self.statusBar().showMessage(f"Loaded session: {fn}", 5000)

    # ====================================================== presets ==
    def _apply_preset(self, start_hz: float, stop_hz: float, points: int) -> None:
        self.sweep_panel.quick_set_band(start_hz, stop_hz, points)
        self._apply_sweep_clicked()

    def _save_current_as_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        cfg = self.sweep_panel.read_config()
        self.presets.add_custom(name.strip(), cfg.start_hz, cfg.stop_hz,
                                cfg.points, hint="(custom)")
        self.cfg["saved_band_presets"] = self.presets.custom_presets()
        save_config(self.cfg)
        self.statusBar().showMessage(f"Saved preset: {name}", 4000)

    # ====================================================== calibration ==
    def _open_cal(self) -> None:
        if not self.controller.connected:
            QMessageBox.information(self, "Not connected", "Connect first.")
            return
        dlg = CalibrationDialog(self.controller, parent=self)
        # When a cal is loaded, the device's sweep grid changes — pull it back
        # so the UI reflects reality.
        dlg.sweep_should_refresh.connect(self._refresh_sweep_from_device)
        dlg.exec()

    def _refresh_sweep_from_device(self) -> None:
        # :VNA:CAL:LOAD? returns success the instant the file parses, but
        # LibreVNA propagates the cal's start/stop/points onto the active
        # sweep over the next frame. Reading immediately would catch the
        # old values, so wait a beat first.
        QTimer.singleShot(350, self._do_refresh_sweep_from_device)

    def _do_refresh_sweep_from_device(self) -> None:
        if not self.controller.connected:
            return
        cfg = self.controller.read_sweep_config()
        if cfg.points <= 0:
            return
        self.sweep_panel.write_config(cfg)
        # The cal range may differ from what's on screen — reset views
        # so the user sees the cal'd band, not the previous one.
        self._reset_all_plot_views()
        self.statusBar().showMessage(
            f"Sweep range pulled from cal: "
            f"{cfg.start_hz/1e6:.2f}–{cfg.stop_hz/1e6:.2f} MHz · {cfg.points} pts",
            5000,
        )

    # ============================================================= csv ==
    def _start_csv_log(self) -> None:
        if self._csv_log_writer is not None:
            QMessageBox.information(self, "CSV log", "Already logging — stop first.")
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "Start CSV log", "vna_log.csv", "CSV (*.csv)"
        )
        if not fn:
            return
        self._csv_log_file = open(fn, "w", newline="", encoding="utf-8")
        self._csv_log_writer = csv.writer(self._csv_log_file)
        self._csv_log_writer.writerow([
            "timestamp", "f_res_Hz", "S11_min_dB", "VSWR",
            "BW_-10dB_Hz", "Fractional_BW_pct",
            "Re(Z)", "Im(Z)", "Q",
        ])
        self._csv_log_file.flush()
        self.statusBar().showMessage(f"CSV log → {fn}", 5000)

    def _stop_csv_log(self) -> None:
        if self._csv_log_file is not None:
            try:
                self._csv_log_file.close()
            except OSError:
                pass
        self._csv_log_writer = None
        self._csv_log_file = None
        self.statusBar().showMessage("CSV log stopped.", 4000)

    # ============================================================ misc ==
    def _on_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"⚠ {msg}", 8000)

    def _on_info(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 4000)

    def _about(self) -> None:
        QMessageBox.about(
            self, "VNA Tester",
            "<h3>VNA Tester</h3>"
            "<p>Antenna-focused measurement front-end for the LibreVNA hardware.</p>"
            "<p>Talks to LibreVNA-GUI's SCPI server (TCP 19542). PyQt6 + pyqtgraph + matplotlib.</p>"
            "<p>Portable — drop on a flash drive together with the LibreVNA folder and go.</p>"
        )

    # ----------------------------------------------------------- close
    def closeEvent(self, ev) -> None:
        self._stop_csv_log()
        self._stop_sweep_worker()
        try:
            self.controller.disconnect()
        except Exception:
            pass
        # Be a good citizen — only kill LibreVNA-GUI if we spawned it.
        try:
            self.launcher.stop()
        except Exception:
            pass
        super().closeEvent(ev)
