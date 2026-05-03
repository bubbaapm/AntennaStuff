"""
Transmission-line and matching calculators tab.
"""
from __future__ import annotations
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QTextEdit, QGridLayout, QCheckBox,
    QGroupBox,
)
from PyQt6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigCanvas
from matplotlib.figure import Figure

from calculators import microstrip, cpw, coax, stripline, matching, physics
from plotting.calc_diagrams import (
    draw_microstrip, draw_cpw, draw_coax, draw_stripline, draw_matching_stub,
)
from plotting.cad import LAYER_COLORS


def _line(default="", width=110):
    le = QLineEdit(default)
    le.setFixedWidth(width)
    return le


def _make_canvas(height: int = 190):
    """Create a small matplotlib canvas with a dark-themed Axes."""
    fig = Figure(figsize=(4.8, height / 60.0))
    fig.patch.set_facecolor(LAYER_COLORS["panel_bg"])
    canvas = FigCanvas(fig)
    canvas.setFixedHeight(height)
    ax = fig.add_subplot(111)
    return fig, canvas, ax


def _redraw(fig, ax, draw_fn, *args, **kwargs):
    """Clear an axes, invoke draw_fn(ax, ...), refresh the canvas."""
    ax.clear()
    draw_fn(ax, *args, **kwargs)
    fig.tight_layout()
    fig.canvas.draw_idle()


class MicrostripCalc(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        L = QVBoxLayout(self)
        # Schematic cross-section at the top
        fig, canvas, ax = _make_canvas(190)
        draw_microstrip(ax)
        fig.tight_layout()
        L.addWidget(canvas)
        form = QFormLayout()
        self.z0 = _line("50")
        self.er = _line("4.4")
        self.h = _line("1.6")
        self.W_in = _line("")
        self.freq = _line("2.4")
        form.addRow("Target Z₀ (Ω):", self.z0)
        form.addRow("εr:", self.er)
        form.addRow("h (mm):", self.h)
        form.addRow("Frequency (GHz):", self.freq)
        form.addRow("(analysis) W (mm):", self.W_in)
        L.addLayout(form)
        row = QHBoxLayout()
        b1 = QPushButton("Synthesize W from Z₀")
        b1.clicked.connect(self._synth)
        b2 = QPushButton("Analyze Z₀ from W")
        b2.clicked.connect(self._analyze)
        row.addWidget(b1); row.addWidget(b2)
        L.addLayout(row)
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setFontFamily("Consolas")
        L.addWidget(self.out)

    def _read(self):
        return (float(self.z0.text()), float(self.er.text()),
                float(self.h.text()) * 1e-3, float(self.freq.text()) * 1e9)

    def _synth(self):
        try:
            z0, er, h, f = self._read()
            r = microstrip.synthesize(z0, er, h)
            att = microstrip.attenuation_db_per_m(r["W"], h, er,
                                                    0.02, f)
            lam_g = physics.wavelength(f, r["Ereff"])
            self.out.setText(
                f"Synthesis result\n"
                f"---------------\n"
                f"W         = {r['W']*1000:.4f} mm     ({r['W_h']:.3f} × h)\n"
                f"W/h       = {r['W_h']:.3f}\n"
                f"εr_eff    = {r['Ereff']:.4f}\n"
                f"Z₀ check  = {r['Z0']:.3f} Ω\n"
                f"λg @ {f/1e9:.2f} GHz = {lam_g*1000:.3f} mm\n"
                f"α_cond    = {att['alpha_c_dB_per_m']:.3f} dB/m\n"
                f"α_diel    = {att['alpha_d_dB_per_m']:.3f} dB/m\n"
                f"α_total   = {att['alpha_total_dB_per_m']:.3f} dB/m"
            )
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _analyze(self):
        try:
            _, er, h, f = self._read()
            W = float(self.W_in.text()) * 1e-3
            r = microstrip.analyze(W, er, h)
            lam_g = physics.wavelength(f, r["Ereff"])
            self.out.setText(
                f"Analysis result\n"
                f"---------------\n"
                f"Z₀      = {r['Z0']:.4f} Ω\n"
                f"εr_eff  = {r['Ereff']:.4f}\n"
                f"W/h     = {r['W_h']:.3f}\n"
                f"λg @ {f/1e9:.2f} GHz = {lam_g*1000:.3f} mm"
            )
        except Exception as e:
            self.out.setText(f"Error: {e}")


class CPWCalc(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        L = QVBoxLayout(self)
        # Schematic cross-section
        self._fig, canvas, self._ax = _make_canvas(200)
        draw_cpw(self._ax, grounded=False)
        self._fig.tight_layout()
        L.addWidget(canvas)
        form = QFormLayout()
        self.z0 = _line("50")
        self.er = _line("4.4")
        self.h = _line("1.6")
        self.s = _line("0.5")
        self.w = _line("0.25")
        self.mode = QComboBox()
        self.mode.addItems(["CPW (infinite substrate)",
                            "Grounded CPW / CBCPW"])
        self.mode.currentIndexChanged.connect(self._update_diagram)
        form.addRow("Target Z₀ (Ω):", self.z0)
        form.addRow("εr:", self.er)
        form.addRow("h (mm):", self.h)
        form.addRow("s — signal width (mm):", self.s)
        form.addRow("w — gap (mm):", self.w)
        form.addRow("Mode:", self.mode)
        L.addLayout(form)
        row = QHBoxLayout()
        b1 = QPushButton("Synthesize s (fix w)")
        b1.clicked.connect(self._synth_s)
        b2 = QPushButton("Synthesize w (fix s)")
        b2.clicked.connect(self._synth_w)
        b3 = QPushButton("Analyze")
        b3.clicked.connect(self._analyze)
        row.addWidget(b1); row.addWidget(b2); row.addWidget(b3)
        L.addLayout(row)
        self.out = QTextEdit()
        self.out.setReadOnly(True); self.out.setFontFamily("Consolas")
        L.addWidget(self.out)

    def _update_diagram(self):
        grounded = self.mode.currentIndex() == 1
        _redraw(self._fig, self._ax, draw_cpw, grounded=grounded)

    def _params(self):
        gr = self.mode.currentIndex() == 1
        return {
            "z0": float(self.z0.text()),
            "er": float(self.er.text()),
            "h": float(self.h.text()) * 1e-3,
            "s": float(self.s.text()) * 1e-3,
            "w": float(self.w.text()) * 1e-3,
            "grounded": gr,
        }

    def _synth_s(self):
        try:
            p = self._params()
            r = cpw.synthesize_cpw(p["z0"], p["er"], p["h"],
                                    w=p["w"], grounded=p["grounded"])
            if "error" in r:
                self.out.setText(r["error"])
                return
            self.out.setText(
                f"CPW synthesis (fixed w)\n"
                f"---------------\n"
                f"s        = {r['s']*1000:.4f} mm\n"
                f"w        = {r['w']*1000:.4f} mm (fixed)\n"
                f"b = s+2w = {r['b']*1000:.4f} mm\n"
                f"Z₀ check = {r['Z0']:.3f} Ω\n"
                f"εr_eff   = {r['Ereff']:.4f}\n"
                f"(Mode: {'GCPW' if p['grounded'] else 'CPW'})"
            )
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _synth_w(self):
        try:
            p = self._params()
            r = cpw.synthesize_cpw_fixed_s(p["z0"], p["er"], p["h"],
                                             s=p["s"], grounded=p["grounded"])
            if "error" in r:
                self.out.setText(r["error"]); return
            self.out.setText(
                f"CPW synthesis (fixed s)\n"
                f"---------------\n"
                f"s        = {r['s']*1000:.4f} mm (fixed)\n"
                f"w        = {r['w']*1000:.4f} mm\n"
                f"b = s+2w = {r['b']*1000:.4f} mm\n"
                f"Z₀ check = {r['Z0']:.3f} Ω\n"
                f"εr_eff   = {r['Ereff']:.4f}"
            )
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _analyze(self):
        try:
            p = self._params()
            r = cpw.analyze_cpw(p["s"], p["w"], p["er"], p["h"],
                                grounded=p["grounded"])
            self.out.setText(
                f"CPW analysis\n"
                f"---------------\n"
                f"Z₀      = {r['Z0']:.3f} Ω\n"
                f"εr_eff  = {r['Ereff']:.4f}\n"
                f"k       = {r['k']:.4f}"
            )
        except Exception as e:
            self.out.setText(f"Error: {e}")


class CoaxCalc(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        L = QVBoxLayout(self)
        fig, canvas, ax = _make_canvas(200)
        draw_coax(ax)
        fig.tight_layout()
        L.addWidget(canvas)
        form = QFormLayout()
        self.z0 = _line("50")
        self.er = _line("2.08")
        self.d  = _line("1.27")
        self.D  = _line("")
        self.f  = _line("6.0")
        form.addRow("Target Z₀ (Ω):", self.z0)
        form.addRow("Dielectric εr:", self.er)
        form.addRow("Inner Ø (mm):", self.d)
        form.addRow("Outer Ø (mm):", self.D)
        form.addRow("Frequency (GHz):", self.f)
        L.addLayout(form)
        row = QHBoxLayout()
        b1 = QPushButton("Outer from Inner"); b1.clicked.connect(self._outer)
        b2 = QPushButton("Inner from Outer"); b2.clicked.connect(self._inner)
        b3 = QPushButton("Analyze Z₀");       b3.clicked.connect(self._analyze)
        row.addWidget(b1); row.addWidget(b2); row.addWidget(b3)
        L.addLayout(row)
        self.out = QTextEdit(); self.out.setReadOnly(True)
        self.out.setFontFamily("Consolas")
        L.addWidget(self.out)

    def _p(self):
        d = float(self.d.text()) * 1e-3 if self.d.text() else None
        D = float(self.D.text()) * 1e-3 if self.D.text() else None
        return (float(self.z0.text()), float(self.er.text()), d, D,
                float(self.f.text()) * 1e9)

    def _outer(self):
        try:
            z0, er, d, _D, f = self._p()
            D = coax.outer_from_inner(d, z0, er)
            self._report(d, D, er, f)
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _inner(self):
        try:
            z0, er, _d, D, f = self._p()
            d = coax.inner_from_outer(D, z0, er)
            self._report(d, D, er, f)
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _analyze(self):
        try:
            _z0, er, d, D, f = self._p()
            Z = coax.impedance_from_diameters(d, D, er)
            self._report(d, D, er, f, Z_override=Z)
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _report(self, d, D, er, f, Z_override=None):
        Z = Z_override if Z_override is not None else \
            coax.impedance_from_diameters(d, D, er)
        fc = coax.te11_cutoff(d, D, er)
        vf = coax.velocity_factor(er)
        C = coax.capacitance_per_length(d, D, er)
        Li = coax.inductance_per_length(d, D)
        self.out.setText(
            f"Coaxial line\n"
            f"---------------\n"
            f"d (inner)   = {d*1000:.4f} mm\n"
            f"D (outer)   = {D*1000:.4f} mm\n"
            f"εr          = {er:.3f}\n"
            f"Z₀          = {Z:.3f} Ω\n"
            f"Velocity factor = {vf:.4f}  (v = {vf*physics.C_LIGHT/1e8:.3f}×10⁸ m/s)\n"
            f"TE₁₁ cutoff = {fc/1e9:.3f} GHz\n"
            f"Operation at {f/1e9:.2f} GHz → {'BELOW cutoff ✓' if f < fc else 'ABOVE cutoff ⚠'}\n"
            f"C' = {C*1e12:.3f} pF/m      L' = {Li*1e9:.3f} nH/m"
        )


class StriplineCalc(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        L = QVBoxLayout(self)
        fig, canvas, ax = _make_canvas(200)
        draw_stripline(ax)
        fig.tight_layout()
        L.addWidget(canvas)
        form = QFormLayout()
        self.z0 = _line("50")
        self.er = _line("3.66")
        self.b = _line("1.6")
        self.t = _line("0.035")
        self.Wm = _line("")
        form.addRow("Target Z₀ (Ω):", self.z0)
        form.addRow("εr:", self.er)
        form.addRow("b — ground separation (mm):", self.b)
        form.addRow("t — copper thickness (mm):", self.t)
        form.addRow("(analysis) W (mm):", self.Wm)
        L.addLayout(form)
        row = QHBoxLayout()
        b1 = QPushButton("Synthesize W"); b1.clicked.connect(self._synth)
        b2 = QPushButton("Analyze Z₀"); b2.clicked.connect(self._analyze)
        row.addWidget(b1); row.addWidget(b2)
        L.addLayout(row)
        self.out = QTextEdit(); self.out.setReadOnly(True)
        self.out.setFontFamily("Consolas")
        L.addWidget(self.out)

    def _synth(self):
        try:
            z0 = float(self.z0.text()); er = float(self.er.text())
            b = float(self.b.text()) * 1e-3; t = float(self.t.text()) * 1e-3
            r = stripline.synthesize(z0, er, b, t)
            self.out.setText(f"Stripline synthesis\n-------------\n"
                             f"W = {r['W']*1000:.4f} mm\n"
                             f"Z₀ check = {r['Z0']:.3f} Ω")
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _analyze(self):
        try:
            er = float(self.er.text())
            b = float(self.b.text()) * 1e-3; t = float(self.t.text()) * 1e-3
            W = float(self.Wm.text()) * 1e-3
            r = stripline.analyze(W, b, er, t)
            self.out.setText(f"Stripline analysis\n----------\n"
                             f"Z₀ = {r['Z0']:.3f} Ω\n"
                             f"W_eff = {r['W_eff']*1000:.4f} mm")
        except Exception as e:
            self.out.setText(f"Error: {e}")


class MatchingCalc(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        L = QVBoxLayout(self)
        self._fig, canvas, self._ax = _make_canvas(210)
        draw_matching_stub(self._ax, open_circuit=True)
        self._fig.tight_layout()
        L.addWidget(canvas)
        form = QFormLayout()
        self.ZA_re = _line("475.22")
        self.ZA_im = _line("8.74")
        self.Z0 = _line("50")
        self.er = _line("3.66")
        self.h = _line("1.6")
        self.f = _line("2.4")
        self.stub_type = QComboBox()
        self.stub_type.addItems(["Open-circuit shunt", "Short-circuit shunt"])
        self.stub_type.currentIndexChanged.connect(self._update_diagram)
        form.addRow("Load ZA real (Ω):", self.ZA_re)
        form.addRow("Load ZA imag (Ω):", self.ZA_im)
        form.addRow("System Z₀ (Ω):", self.Z0)
        form.addRow("εr:", self.er)
        form.addRow("h (mm):", self.h)
        form.addRow("Frequency (GHz):", self.f)
        form.addRow("Stub type:", self.stub_type)
        L.addLayout(form)
        row = QHBoxLayout()
        b1 = QPushButton("Single shunt stub"); b1.clicked.connect(self._stub)
        b2 = QPushButton("λ/4 transformer (real ZA)")
        b2.clicked.connect(self._qw)
        b3 = QPushButton("L-network (lumped)"); b3.clicked.connect(self._lnet)
        row.addWidget(b1); row.addWidget(b2); row.addWidget(b3)
        L.addLayout(row)
        self.out = QTextEdit(); self.out.setReadOnly(True)
        self.out.setFontFamily("Consolas")
        L.addWidget(self.out)

    def _update_diagram(self):
        oc = self.stub_type.currentIndex() == 0
        _redraw(self._fig, self._ax, draw_matching_stub, open_circuit=oc)

    def _ctx(self):
        return {"ZA": complex(float(self.ZA_re.text()), float(self.ZA_im.text())),
                "Z0": float(self.Z0.text()),
                "er": float(self.er.text()),
                "h": float(self.h.text()) * 1e-3,
                "f": float(self.f.text()) * 1e9}

    def _stub(self):
        try:
            c = self._ctx()
            ms = microstrip.synthesize(c["Z0"], c["er"], c["h"])
            lam_g = physics.wavelength(c["f"], ms["Ereff"])
            sols = matching.shunt_stub(
                c["ZA"], c["Z0"],
                open_circuit=self.stub_type.currentIndex() == 0)
            lines = [f"Single shunt stub  (feed W = {ms['W']*1000:.3f} mm, "
                     f"λg = {lam_g*1000:.3f} mm):", "-"*50]
            for i, s in enumerate(sols, 1):
                d = s["d_over_lambda"] * lam_g * 1000
                l = s["l_over_lambda"] * lam_g * 1000
                lines.append(
                    f"  [{i}] d = {d:8.3f} mm ({s['d_over_lambda']*360:6.2f}°)    "
                    f"l = {l:8.3f} mm ({s['l_over_lambda']*360:6.2f}°)")
            self.out.setText("\n".join(lines))
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _qw(self):
        try:
            c = self._ctx()
            if abs(c["ZA"].imag) > 1e-3:
                self.out.setText("λ/4 transformer requires real-valued load "
                                 "(got j-imag). Strip reactance first.")
                return
            r = matching.quarter_wave(c["ZA"].real, c["Z0"])
            ms = microstrip.synthesize(r["Z_transformer"], c["er"], c["h"])
            lam_g = physics.wavelength(c["f"], ms["Ereff"])
            self.out.setText(
                f"λ/4 transformer\n---------\n"
                f"Z_trans = {r['Z_transformer']:.3f} Ω\n"
                f"W       = {ms['W']*1000:.3f} mm\n"
                f"Length  = {lam_g/4*1000:.3f} mm  (λg/4)"
            )
        except Exception as e:
            self.out.setText(f"Error: {e}")

    def _lnet(self):
        try:
            c = self._ctx()
            sols = matching.l_network(c["ZA"], c["Z0"], c["f"])
            if not sols:
                self.out.setText("No L-network solution for this ZA / Z0.")
                return
            lines = ["L-network solutions:", "-"*50]
            for i, s in enumerate(sols, 1):
                lines.append(f"  [{i}] {s['topology']}")
                lines.append(f"       Series element: {s['series']}")
                lines.append(f"       Shunt element:  {s['shunt']}")
            self.out.setText("\n".join(lines))
        except Exception as e:
            self.out.setText(f"Error: {e}")


class CalculatorsTab(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addTab(MicrostripCalc(), "Microstrip")
        self.addTab(CPWCalc(), "CPW / GCPW")
        self.addTab(CoaxCalc(), "Coaxial")
        self.addTab(StriplineCalc(), "Stripline")
        self.addTab(MatchingCalc(), "Matching")
