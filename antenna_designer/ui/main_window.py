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
    QToolBar, QPushButton, QCheckBox,
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
        self._has_computed_once = False

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

        # Tab 4 — 2D Radiation (with a "Show antenna" toggle above the canvas)
        self.fig_rad2, self.canvas_rad2 = _mk_canvas(figsize=(8, 5))
        self.chk_show_geom_2d = QCheckBox("Show antenna geometry")
        self.chk_show_geom_2d.setChecked(True)
        self.chk_show_geom_2d.setToolTip(
            "Add a top-down view of the antenna above the polar plots so you "
            "can see how the beam direction maps to the physical layout.")
        self.chk_show_geom_2d.toggled.connect(self._redraw_pattern_2d_if_ready)
        self.tabs.addTab(
            self._wrap_canvas_with_check(self.canvas_rad2,
                                         [self.chk_show_geom_2d]),
            "2D Radiation Pattern")

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

    def _wrap_canvas_with_check(self, canvas, extra_widgets):
        """Like _wrap_canvas but appends extra widgets (checkboxes etc.) to
        the toolbar row."""
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(2, 2, 2, 2)
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        toolbar = NavTB(canvas, w)
        toolbar.setStyleSheet("background: #242424; color: #e0e0e0;")
        row.addWidget(toolbar)
        for ew in extra_widgets:
            row.addWidget(ew)
        row.addStretch(1)
        bar_w = QWidget(); bar_w.setLayout(row)
        v.addWidget(bar_w)
        v.addWidget(canvas, 1)
        return w

    def _redraw_pattern_2d_if_ready(self):
        if self._last_antenna and self._last_ctx and self._last_results is not None:
            self._draw_pattern_2d(self._last_antenna, self._last_ctx,
                                  self._last_results)

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
        export_m = file_m.addMenu("Export CST / geometry")
        a_cst_full = QAction("CST full tunable model (.bas)…", self)
        a_cst_full.setToolTip(
            "Build the whole antenna in CST from Parameter List variables "
            "and history commands. This is the preferred path for tuning: "
            "edit W, L, feed offsets, substrate thickness, etc. in CST and "
            "Rebuild. Run from CST's macro editor; do not import the .bas "
            "into the History List as a nested RunScript.")
        a_cst_full.triggered.connect(self._export_cst_full_model)
        export_m.addAction(a_cst_full)
        a_cst_ps = QAction("CST direct builder PowerShell (.ps1)…", self)
        a_cst_ps.setToolTip(
            "Launch CST through COM and add the generated model directly to "
            "the History List with AddToHistory. Use this for external "
            "automation; it avoids CST's unsupported nested RunScript path.")
        a_cst_ps.triggered.connect(self._export_cst_powershell_builder)
        export_m.addAction(a_cst_ps)
        export_m.addSeparator()
        a_dxf_all = QAction("DXF — single combined .dxf (recommended)…", self)
        a_dxf_all.setToolTip("One .dxf file containing every curve as a "
                             "separate POLYLINE on its own layer, plus the "
                             "substrate-outline rectangle. Import once in "
                             "CST → Curves → New Curve → Import.")
        a_dxf_all.triggered.connect(self._export_geometry_dxf_combined)
        export_m.addAction(a_dxf_all)
        a_dxf = QAction("DXF — one .dxf per curve…", self)
        a_dxf.setToolTip("Each curve as its own .dxf file. Use this if "
                         "you want curve-by-curve control over which "
                         "polyline gets imported.")
        a_dxf.triggered.connect(self._export_geometry_dxf_per_curve)
        export_m.addAction(a_dxf)
        a_cst_an = QAction("CST analytical-curve text (.txt)…", self)
        a_cst_an.setToolTip("Pre-formatted X(t), Y(t), Z(t) blocks ready to "
                            "paste into CST → Curves → Create Analytical Curve.")
        a_cst_an.triggered.connect(self._export_geometry_cst_analytical)
        export_m.addAction(a_cst_an)
        a_cst_vba = QAction("CST VBA macro — feed + port (.bas)…", self)
        a_cst_vba.setToolTip(
            "Parametric assembly script for the bottom-layer feed + radial "
            "stub, plus a free-coordinate waveguide port at the feed launch. "
            "Paste into CST's History List (or save and run via Macros → Run "
            "Macro). All dimensions reference the CST Parameter List so you "
            "can sweep them after import.")
        a_cst_vba.triggered.connect(self._export_geometry_cst_vba)
        export_m.addAction(a_cst_vba)
        a_spline = QAction("CST spline points — one .txt per curve…", self)
        a_spline.setToolTip("Pick a folder. Each curve is saved as its own "
                            "ASCII-pure 'x y z' TXT — no headers, no unicode, "
                            "no comments. Ready for CST → Curves → Curve "
                            "from File. Use this if your previous TXT "
                            "imports failed.")
        a_spline.triggered.connect(self._export_geometry_spline_per_curve)
        export_m.addAction(a_spline)
        a_spline1 = QAction("CST spline points — single combined .txt…", self)
        a_spline1.setToolTip("All curves in one file, blank-line separated. "
                             "Some CST versions need the per-curve variant "
                             "above instead.")
        a_spline1.triggered.connect(self._export_geometry_spline_txt)
        export_m.addAction(a_spline1)
        a_csv = QAction("Generic CSV (.csv)…", self)
        a_csv.setToolTip("Comma-separated values with headers — for "
                         "spreadsheets / scripts.")
        a_csv.triggered.connect(self._export_geometry_csv)
        export_m.addAction(a_csv)
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
            # On the very first compute, surface the CAD tab so the user sees
            # the antenna they just made. On subsequent recomputes (e.g. F5
            # tweaks), respect whatever tab they're already on so iterating
            # doesn't bounce them away from the Calculators / 3D view.
            if not self._has_computed_once:
                self.tabs.setCurrentIndex(1)
            self._has_computed_once = True
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Compute error",
                                 f"{type(e).__name__}: {e}")

    def _draw_pattern_2d(self, ant, ctx, results):
        self.fig_rad2.clf()
        cuts = ant.pattern_cuts(ctx, results)
        fom = ant.figures_of_merit(ctx, results) or {}
        hpbw_e = fom.get("HPBW_E_deg", float("nan"))
        hpbw_h = fom.get("HPBW_H_deg", float("nan"))

        show_geom = (self.chk_show_geom_2d.isChecked()
                     if hasattr(self, "chk_show_geom_2d") else False)
        if show_geom:
            # Geometry on top, two polar cuts below. Generous hspace so the
            # polar titles don't crash into the geometry inset's axes.
            gs = self.fig_rad2.add_gridspec(2, 2, height_ratios=[1.0, 2.0],
                                            hspace=0.55, wspace=0.20)
            ax_geom = self.fig_rad2.add_subplot(gs[0, :])
            try:
                # Stripped-down outline view (NOT the full CAD plot — its
                # dimension labels turn into illegible noise at inset size).
                ant.plot_outline_overview(ax_geom, ctx, results)
            except Exception as e:
                ax_geom.text(0.5, 0.5, f"Geometry overlay error:\n{e}",
                             ha="center", va="center",
                             transform=ax_geom.transAxes, color="red")
                ax_geom.set_axis_off()
            ax1 = self.fig_rad2.add_subplot(gs[1, 0], projection="polar")
            ax2 = self.fig_rad2.add_subplot(gs[1, 1], projection="polar")
        else:
            ax1 = self.fig_rad2.add_subplot(121, projection="polar")
            ax2 = self.fig_rad2.add_subplot(122, projection="polar")
        # In overlay mode, render the per-plot title+peak readout INSIDE the
        # polar axes as a footer line so the labels don't crash into the
        # geometry inset above.
        _label_inside = show_geom

        def _draw_cut(ax, angles, U, color, title):
            """Plot one principal-plane cut with the beam rotated to the top.

            Both polar plots use the standard antenna-engineering convention
            of "boresight at 0° (top)" so the same physical direction is at
            the same screen position regardless of which cut you're looking
            at. The polar tick labels therefore read as 'angle from beam',
            not absolute θ/φ; the footer line reports the original data
            angle of the peak for cross-reference.
            """
            from antennas.base import _hpbw_from_cut
            U = np.asarray(U)
            Umax = U.max() if U.size else 0.0
            if Umax <= 0:
                if _label_inside:
                    ax.text(0.5, -0.10, title, transform=ax.transAxes,
                            ha="center", va="top",
                            color=LAYER_COLORS["text"], fontsize=9)
                else:
                    ax.set_title(title, color=LAYER_COLORS["text"],
                                 fontsize=10, pad=12)
                return

            U_safe = np.maximum(U, 1e-5)
            Udb = np.clip(20 * np.log10(U_safe / Umax), -40, 0)

            # Rotate the polar so the peak sits at 0° (top with N origin).
            ipk = int(np.argmax(U))
            pk_data_deg = float(np.degrees(angles[ipk])) % 360.0
            rotated = (angles - angles[ipk]) % (2 * np.pi)
            order = np.argsort(rotated)
            a_p = np.concatenate([rotated[order], [2 * np.pi]])
            Udb_p = np.concatenate([Udb[order], [Udb[order][0]]])

            ax.plot(a_p, Udb_p + 40, color=color, lw=2)
            ax.fill(a_p, Udb_p + 40, color=color, alpha=0.25)
            ax.set_rmax(40); ax.set_rticks([10, 20, 30, 40])
            ax.set_yticklabels(["-30", "-20", "-10", "0 dB"])
            ax.grid(True, alpha=0.5)
            # Peak marker (now always at polar 0° = top) + −3 dB ring
            ax.plot([0], [Udb[ipk] + 40], "o", color="#ffffff",
                    markersize=5, zorder=5)
            ax.plot(a_p, np.full_like(a_p, 37.0),
                    color="#888", ls="--", lw=0.7, alpha=0.7)

            hpbw = _hpbw_from_cut(angles, U)
            sub = f"beam @ data {pk_data_deg:.1f}°"
            if np.isfinite(hpbw):
                sub += f"   HPBW = {hpbw:.1f}°"
            if _label_inside:
                ax.text(0.5, -0.10, f"{title}   {sub}",
                        transform=ax.transAxes, ha="center", va="top",
                        color=LAYER_COLORS["text"], fontsize=9)
            else:
                ax.set_title(title + "\n" + sub,
                             color=LAYER_COLORS["text"], fontsize=10, pad=12)

        # Both plots use the same polar convention so the beam direction
        # appears in the same screen position. θ=0 (top), counter-clockwise.
        for ax in (ax1, ax2):
            style_ax(self.fig_rad2, ax, "", equal=False, grid=True)
            ax.set_theta_zero_location("N")
            ax.set_theta_direction(-1)  # clockwise — 90° on the right

        _draw_cut(ax1, cuts["theta_e"], cuts["U_e"],
                  "#00e0b4", "E-plane (φ=0°)")
        _draw_cut(ax2, cuts["phi_a"], cuts["U_a"],
                  "#ffd34d", "H-plane (θ=90°)")

        if not show_geom:
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
                self.input_panel.set_extra(k, v)
            self.statusBar().showMessage(f"Loaded: {fn}")
            self._do_compute()
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))

    def _have_results(self) -> bool:
        if (self._last_antenna is None or self._last_ctx is None
                or self._last_results is None):
            QMessageBox.information(self, "Nothing to export",
                                    "Compute an antenna first.")
            return False
        return True

    def _export_geometry_csv(self):
        if not self._have_results():
            return
        default = f"{self._last_antenna_name.replace(' ', '_')}_curves.csv"
        fn, _ = QFileDialog.getSaveFileName(self, "Export curves (CSV)",
                                            default, "CSV (*.csv)")
        if not fn:
            return
        try:
            text = self._last_antenna.export_geometry_csv(
                self._last_ctx, self._last_results)
            Path(fn).write_text(text, encoding="utf-8")
            self.statusBar().showMessage(f"Wrote CSV to: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", f"{type(e).__name__}: {e}")

    def _export_geometry_cst_analytical(self):
        if not self._have_results():
            return
        default = f"{self._last_antenna_name.replace(' ', '_')}_cst_analytical.txt"
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export CST analytical-curve text", default,
            "Text (*.txt)")
        if not fn:
            return
        try:
            text = self._last_antenna.export_cst_analytical_text(
                self._last_ctx, self._last_results)
            Path(fn).write_text(text, encoding="utf-8")
            self.statusBar().showMessage(
                f"Wrote CST analytical-curve text to: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", f"{type(e).__name__}: {e}")

    def _export_geometry_cst_vba(self):
        if not self._have_results():
            return
        macro = self._last_antenna.export_cst_vba_macro(
            self._last_ctx, self._last_results)
        if not macro.strip():
            QMessageBox.information(
                self, "No VBA macro",
                "This antenna does not currently emit a CST VBA macro.\n\n"
                "Only antennas with non-trivial bottom-layer geometry "
                "(e.g. Vivaldi) provide one. For everything else, the "
                "DXF + analytical-curve exports are enough.")
            return
        default = f"{self._last_antenna_name.replace(' ', '_')}_cst.bas"
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export CST VBA macro", default,
            "VBA macro (*.bas);;Text (*.txt)")
        if not fn:
            return
        try:
            # Non-ASCII chars only appear in comments; UTF-8 is fine for CST.
            Path(fn).write_text(macro, encoding="utf-8")
            self.statusBar().showMessage(f"Wrote CST VBA macro to: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Export error",
                                 f"{type(e).__name__}: {e}")

    def _export_cst_full_model(self):
        if not self._have_results():
            return
        macro = self._last_antenna.export_cst_full_model_macro(
            self._last_ctx, self._last_results)
        if not macro.strip():
            QMessageBox.information(
                self, "No full CST model builder",
                "This antenna does not yet provide a full tunable CST model "
                "builder.\n\nUse this exporter when available for CST tuning. "
                "DXF, spline, and analytical-curve exports are still useful "
                "for inspection or manual assembly, but they are not the same "
                "as a parameter-list-driven CST history model.")
            return
        default = f"{self._last_antenna_name.replace(' ', '_')}_full_cst_model.bas"
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export full tunable CST model", default,
            "VBA macro (*.bas);;Text (*.txt)")
        if not fn:
            return
        try:
            Path(fn).write_text(self._annotate_cst_macro(macro), encoding="utf-8")
            self.statusBar().showMessage(
                f"Wrote full tunable CST model macro to: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Export error",
                                 f"{type(e).__name__}: {e}")

    def _macro_body_for_add_to_history(self, macro: str) -> str:
        """Return the Sub Main body so COM can call AddToHistory directly."""
        lines = macro.splitlines()
        start = 0
        end = len(lines)
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("sub main"):
                start = i + 1
                break
        for i in range(start, len(lines)):
            if lines[i].strip().lower() == "end sub":
                end = i
                break
        return "\n".join(lines[start:end]).strip() + "\n"

    def _annotate_cst_macro(self, macro: str) -> str:
        note = (
            "' IMPORTANT:\n"
            "'   Run this from CST: Macros > Edit/Run VBA Macro.\n"
            "'   Do NOT use File > Import BAS-file into History List, and do\n"
            "'   NOT call it through RunScript from another macro. CST rejects\n"
            "'   nested RunScript calls that try to update the History List.\n"
            "'   For external automation, export the PowerShell builder instead.\n"
            "'\n"
        )
        return note + macro

    def _export_cst_powershell_builder(self):
        if not self._have_results():
            return
        macro = self._last_antenna.export_cst_full_model_macro(
            self._last_ctx, self._last_results)
        if not macro.strip():
            QMessageBox.information(
                self, "No full CST model builder",
                "This antenna does not yet provide a full tunable CST model "
                "builder.")
            return
        body = self._macro_body_for_add_to_history(macro)
        name = self._last_antenna_name.replace("'", "").replace("\n", " ")
        ps = (
            "# Generated by Antenna Designer\n"
            "# Launches CST and creates a parameter-list-driven model using\n"
            "# AddToHistory. This avoids CST's unsupported nested RunScript path.\n"
            "$cst = New-Object -ComObject CSTStudio.application\n"
            "$mws = $cst.NewMWS()\n"
            "$history = @'\n"
            f"{body}"
            "'@\n"
            f"$mws.AddToHistory('Build tunable model - {name}', $history)\n"
            "$mws.Rebuild()\n"
            "Write-Host 'CST tunable model created.'\n"
        )
        default = f"{self._last_antenna_name.replace(' ', '_')}_cst_builder.ps1"
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export CST PowerShell builder", default,
            "PowerShell (*.ps1);;Text (*.txt)")
        if not fn:
            return
        try:
            Path(fn).write_text(ps, encoding="utf-8")
            self.statusBar().showMessage(f"Wrote CST PowerShell builder to: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Export error",
                                 f"{type(e).__name__}: {e}")

    def _export_geometry_spline_txt(self):
        if not self._have_results():
            return
        default = f"{self._last_antenna_name.replace(' ', '_')}_spline.txt"
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export spline points (single combined TXT)", default,
            "Text (*.txt)")
        if not fn:
            return
        try:
            text = self._last_antenna.export_spline_txt(
                self._last_ctx, self._last_results, include_header=False)
            # ASCII-only write (CST 2023 chokes on UTF-8 BOM in spline files)
            Path(fn).write_text(text, encoding="ascii", errors="replace")
            self.statusBar().showMessage(f"Wrote spline TXT to: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", f"{type(e).__name__}: {e}")

    def _export_geometry_dxf_combined(self):
        if not self._have_results():
            return
        default = f"{self._last_antenna_name.replace(' ', '_')}.dxf"
        fn, _ = QFileDialog.getSaveFileName(
            self, "Export combined DXF (all curves in one file)",
            default, "DXF (*.dxf)")
        if not fn:
            return
        try:
            text = self._last_antenna.export_combined_dxf(
                self._last_ctx, self._last_results)
            Path(fn).write_bytes(text.encode("ascii", errors="replace"))
            self.statusBar().showMessage(f"Wrote combined DXF to: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", f"{type(e).__name__}: {e}")

    def _export_geometry_dxf_per_curve(self):
        if not self._have_results():
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "Pick output folder — one DXF per curve will be saved here")
        if not out_dir:
            return
        try:
            files = self._last_antenna.export_dxf_per_curve(
                self._last_ctx, self._last_results)
            if not files:
                QMessageBox.information(self, "Nothing to export",
                                        "This antenna doesn't declare any "
                                        "parametric curves.")
                return
            for name, content in files:
                (Path(out_dir) / name).write_bytes(content.encode("ascii",
                                                                   errors="replace"))
            QMessageBox.information(
                self, "DXF export",
                f"Wrote {len(files)} DXF files to:\n{out_dir}\n\n"
                + "\n".join(f"  • {n}" for n, _ in files)
                + "\n\nCST: Curves → Curve → New Curve → Import.")
            self.statusBar().showMessage(
                f"Wrote {len(files)} DXF files to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", f"{type(e).__name__}: {e}")

    def _export_geometry_spline_per_curve(self):
        if not self._have_results():
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "Pick output folder — one TXT per curve will be saved here")
        if not out_dir:
            return
        try:
            files = self._last_antenna.export_spline_txt_per_curve(
                self._last_ctx, self._last_results)
            if not files:
                QMessageBox.information(self, "Nothing to export",
                                        "This antenna doesn't declare any "
                                        "parametric curves.")
                return
            written = []
            for name, content in files:
                p = Path(out_dir) / name
                p.write_text(content, encoding="ascii", errors="replace")
                written.append(name)
            QMessageBox.information(
                self, "Spline TXT export",
                f"Wrote {len(written)} files to:\n{out_dir}\n\n"
                + "\n".join(f"  • {n}" for n in written))
            self.statusBar().showMessage(
                f"Wrote {len(written)} TXT files to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export error", f"{type(e).__name__}: {e}")

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
