"""
Main application window.
"""
from __future__ import annotations
import json
import traceback
from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTextEdit, QLabel, QStatusBar, QMessageBox, QFileDialog, QDockWidget,
    QToolBar, QPushButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QFont

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavTB

from antennas import available_antennas, get_antenna, Context
from plotting.cad import LAYER_COLORS, style_ax
from plotting.radiation3d import Radiation3DView
from .input_panel import InputPanel
from .calculators_tab import CalculatorsTab


def _mk_canvas(figsize=(6, 5)):
    fig = Figure(figsize=figsize)
    fig.patch.set_facecolor(LAYER_COLORS["panel_bg"])
    canvas = FigureCanvas(fig)
    return fig, canvas


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Elite Antenna Designer v2")
        self.resize(1600, 980)

        self._last_results = None
        self._last_ctx = None
        self._last_antenna_name = None
        self._last_antenna = None

        self._build_ui()
        self._build_menu()

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self.input_panel = InputPanel()
        self.input_panel.setMinimumWidth(370)
        self.input_panel.setMaximumWidth(460)
        self.input_panel.request_compute.connect(self._do_compute)
        self.input_panel.antenna_changed.connect(self._on_antenna_changed)
        splitter.addWidget(self.input_panel)

        # Right side: tabs
        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # Tab 1 — Dimensions & Info
        self.text_out = QTextEdit()
        self.text_out.setReadOnly(True)
        font = QFont("Consolas"); font.setPointSize(10)
        self.text_out.setFont(font)
        self.tabs.addTab(self.text_out, "Dimensions && Info")

        # Tab 2 — CAD Geometry
        self.fig_cad, self.canvas_cad = _mk_canvas()
        self.tabs.addTab(self._wrap_canvas(self.canvas_cad), "CAD Geometry")

        # Tab 3 — E-Field / Currents
        self.fig_field, self.canvas_field = _mk_canvas()
        self.tabs.addTab(self._wrap_canvas(self.canvas_field), "E-Field / Currents")

        # Tab 4 — 2D Radiation
        self.fig_rad2, self.canvas_rad2 = _mk_canvas(figsize=(8, 4))
        self.tabs.addTab(self._wrap_canvas(self.canvas_rad2), "2D Radiation Pattern")

        # Tab 5 — 3D Radiation
        self.rad3d = Radiation3DView()
        self.tabs.addTab(self.rad3d, "3D Radiation Pattern")

        # Tab 6 — Calculators
        self.calc_tab = CalculatorsTab()
        self.tabs.addTab(self.calc_tab, "Calculators")

        splitter.setSizes([400, 1200])

        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready. Select an antenna and press Calculate.")

    def _wrap_canvas(self, canvas):
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(2, 2, 2, 2)
        toolbar = NavTB(canvas, w)
        toolbar.setStyleSheet("background: #242424; color: #e0e0e0;")
        v.addWidget(toolbar)
        v.addWidget(canvas, 1)
        return w

    def _build_menu(self):
        mb = self.menuBar()

        file_m = mb.addMenu("&File")
        a_save = QAction("Save design…", self)
        a_save.setShortcut(QKeySequence.StandardKey.Save)
        a_save.triggered.connect(self._save_design)
        file_m.addAction(a_save)
        a_load = QAction("Load design…", self)
        a_load.setShortcut(QKeySequence.StandardKey.Open)
        a_load.triggered.connect(self._load_design)
        file_m.addAction(a_load)
        file_m.addSeparator()
        a_exp = QAction("Export current plot (PNG)…", self)
        a_exp.triggered.connect(self._export_current_plot)
        file_m.addAction(a_exp)
        file_m.addSeparator()
        a_quit = QAction("Quit", self)
        a_quit.setShortcut(QKeySequence.StandardKey.Quit)
        a_quit.triggered.connect(self.close)
        file_m.addAction(a_quit)

        view_m = mb.addMenu("&View")
        a_recalc = QAction("Recalculate", self)
        a_recalc.setShortcut("F5")
        a_recalc.triggered.connect(self._do_compute)
        view_m.addAction(a_recalc)

        help_m = mb.addMenu("&Help")
        a_about = QAction("About", self)
        a_about.triggered.connect(self._about)
        help_m.addAction(a_about)

    # -------------------------------------------------------------- actions
    def _on_antenna_changed(self, name):
        self.statusBar().showMessage(f"Selected: {name}")

    def _do_compute(self):
        try:
            ctx = self.input_panel.read_context()
            params = self.input_panel.read_params()
            name = self.input_panel.current_antenna()
            ant = get_antenna(name)
            results = ant.compute(ctx, params)

            self._last_ctx = ctx
            self._last_results = results
            self._last_antenna_name = name
            self._last_antenna = ant

            # Text summary
            summary = ant.summary(ctx, results)
            fom = ant.figures_of_merit(ctx, results)
            if fom:
                summary += "\n\nFigures of merit (from pattern integration):\n"
                for k, v in fom.items():
                    summary += f"  {k:<18s} = {v:.3f}\n"
            self.text_out.setPlainText(summary)

            # Geometry plot
            self.fig_cad.clf()
            ax = self.fig_cad.add_subplot(111)
            try:
                ant.plot_geometry(ax, ctx, results)
            except Exception as e:
                ax.text(0.5, 0.5, f"Geometry error:\n{e}",
                        ha="center", va="center", transform=ax.transAxes,
                        color="red")
                ax.set_axis_off()
            self.canvas_cad.draw_idle()

            # Field plot
            self.fig_field.clf()
            ax = self.fig_field.add_subplot(111)
            try:
                ant.plot_fields(ax, ctx, results)
            except Exception as e:
                ax.text(0.5, 0.5, f"Field plot error:\n{e}",
                        ha="center", va="center", transform=ax.transAxes,
                        color="red")
                ax.set_axis_off()
            self.canvas_field.draw_idle()

            # 2D pattern
            self._draw_pattern_2d(ant, ctx, results)

            # 3D pattern
            self.rad3d.set_pattern(ctx, results, ant.pattern)

            self.statusBar().showMessage(f"Computed: {name} ✓")
            self.tabs.setCurrentIndex(1)  # jump to CAD view
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Compute error",
                                 f"{type(e).__name__}: {e}")

    def _draw_pattern_2d(self, ant, ctx, results):
        self.fig_rad2.clf()
        cuts = ant.pattern_cuts(ctx, results)
        # E-plane (elevation, varying θ, φ=0)
        ax1 = self.fig_rad2.add_subplot(121, projection="polar")
        style_ax(self.fig_rad2, ax1, "E-plane (φ=0°)  — θ vs |U|", equal=False, grid=True)
        U_e = np.maximum(cuts["U_e"], 1e-5)
        Udb_e = 20 * np.log10(U_e)
        Udb_e = np.clip(Udb_e, -40, 0)
        ax1.plot(cuts["theta_e"], Udb_e + 40, color="#00e0b4", lw=2)
        ax1.fill(cuts["theta_e"], Udb_e + 40, color="#00e0b4", alpha=0.25)
        ax1.set_theta_zero_location("N")
        ax1.set_rmax(40); ax1.set_rticks([10, 20, 30, 40])
        ax1.set_yticklabels(["-30", "-20", "-10", "0 dB"])
        ax1.grid(True, alpha=0.5)

        # H-plane (azimuth, θ=90°, varying φ)
        ax2 = self.fig_rad2.add_subplot(122, projection="polar")
        style_ax(self.fig_rad2, ax2, "H-plane (θ=90°) — φ vs |U|", equal=False, grid=True)
        U_a = np.maximum(cuts["U_a"], 1e-5)
        Udb_a = 20 * np.log10(U_a)
        Udb_a = np.clip(Udb_a, -40, 0)
        ax2.plot(cuts["phi_a"], Udb_a + 40, color="#ffd34d", lw=2)
        ax2.fill(cuts["phi_a"], Udb_a + 40, color="#ffd34d", alpha=0.25)
        ax2.set_theta_zero_location("E")
        ax2.set_rmax(40); ax2.set_rticks([10, 20, 30, 40])
        ax2.set_yticklabels(["-30", "-20", "-10", "0 dB"])
        ax2.grid(True, alpha=0.5)

        self.fig_rad2.tight_layout()
        self.canvas_rad2.draw_idle()

    def _save_design(self):
        if self._last_ctx is None:
            QMessageBox.information(self, "Nothing to save",
                                    "Calculate an antenna first.")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Save design as JSON",
                                            "antenna_design.json",
                                            "JSON (*.json)")
        if not fn:
            return
        ctx = self._last_ctx
        data = {
            "antenna": self._last_antenna_name,
            "base": {
                "fr_hz": ctx.fr, "er": ctx.er, "z0": ctx.z0,
                "h_m": ctx.h, "Ls_m": ctx.Ls, "Ws_m": ctx.Ws,
                "loss_tangent": ctx.loss_tangent,
                "unit_str": ctx.unit_str, "out_mult": ctx.out_mult,
            },
            "params": self.input_panel.read_params(),
        }
        Path(fn).write_text(json.dumps(data, indent=2))
        self.statusBar().showMessage(f"Saved: {fn}")

    def _load_design(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Load design JSON", "",
                                            "JSON (*.json)")
        if not fn:
            return
        try:
            data = json.loads(Path(fn).read_text())
            # Restore antenna + params
            name = data["antenna"]
            # Find category
            for cat, names in available_antennas().items():
                if name in names:
                    self.input_panel.cb_cat.setCurrentText(cat)
                    break
            self.input_panel.cb_ant.setCurrentText(name)
            base = data["base"]
            conv = 2.54e-5 if base["unit_str"] == "mils" else 1e-3
            self.input_panel.fr.setText(f"{base['fr_hz']/1e9:g}")
            self.input_panel.er.setText(f"{base['er']:g}")
            self.input_panel.z0.setText(f"{base['z0']:g}")
            self.input_panel.h.setText(f"{base['h_m']/conv:g}")
            self.input_panel.Ls.setText(f"{base['Ls_m']/conv:g}")
            self.input_panel.Ws.setText(f"{base['Ws_m']/conv:g}")
            self.input_panel.loss_tan.setText(f"{base['loss_tangent']:g}")
            self.input_panel.cb_unit.setCurrentText(base["unit_str"])
            # Restore extras
            for k, v in data.get("params", {}).items():
                if k in self.input_panel._extra_inputs:
                    self.input_panel._extra_inputs[k].setText(str(v))
            self.statusBar().showMessage(f"Loaded: {fn}")
            self._do_compute()
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))

    def _export_current_plot(self):
        idx = self.tabs.currentIndex()
        fig = None
        if idx == 1: fig = self.fig_cad
        elif idx == 2: fig = self.fig_field
        elif idx == 3: fig = self.fig_rad2
        if fig is None:
            QMessageBox.information(self, "Export",
                                    "Select the CAD, Field, or 2D Pattern tab first.")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Export plot", "plot.png",
                                            "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if fn:
            fig.savefig(fn, dpi=200, facecolor=LAYER_COLORS["panel_bg"])
            self.statusBar().showMessage(f"Exported: {fn}")

    def _about(self):
        QMessageBox.about(
            self, "Elite Antenna Designer",
            "<h3>Elite Antenna Designer v2</h3>"
            "<p>Modular antenna synthesis & visualization tool.</p>"
            "<p>PyQt6 + matplotlib + pyqtgraph.opengl</p>"
            "<p>Math: Balanis, Pozar, Wadell, Simons.</p>"
        )
