"""
Dynamic input panel — left-side scrollable area that renders fields based on
the selected antenna.
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QLabel,
    QPushButton, QGroupBox, QScrollArea, QHBoxLayout, QSpinBox,
    QDoubleSpinBox, QMessageBox,
)
from PyQt6.QtCore import pyqtSignal, Qt

from antennas import available_antennas, get_antenna, Context, C_LIGHT
from calculators.physics import SUBSTRATES


class InputPanel(QScrollArea):
    request_compute = pyqtSignal()
    antenna_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._root = QWidget()
        self.setWidget(self._root)

        # Must exist before _antenna_changed is triggered by combo population
        self._extra_inputs: dict[str, QLineEdit] = {}
        self.extra_form = QFormLayout()
        self.extra_widget = QWidget()
        self.extra_widget.setLayout(self.extra_form)

        v = QVBoxLayout(self._root)
        v.setContentsMargins(8, 8, 8, 8)

        v.addWidget(self._h_title("Antenna selection"))

        # Category + antenna selector
        self.cb_cat = QComboBox()
        self.cb_ant = QComboBox()
        cats = available_antennas()
        for c in cats.keys():
            self.cb_cat.addItem(c)
        self._populate_antennas(self.cb_cat.currentText())
        self.cb_cat.currentTextChanged.connect(self._populate_antennas)
        self.cb_ant.currentTextChanged.connect(self._antenna_changed)
        form = QFormLayout()
        form.addRow("Category:", self.cb_cat)
        form.addRow("Antenna:",  self.cb_ant)
        v.addLayout(form)

        # Base-parameter group
        v.addWidget(self._h_title("Base parameters"))
        self.base_form = QFormLayout()
        self.fr = QLineEdit("5.35")
        self.z0 = QLineEdit("50")
        self.Ls = QLineEdit("15")
        self.Ws = QLineEdit("15")
        self.loss_tan = QLineEdit("0.02")

        self.cb_unit = QComboBox()
        self.cb_unit.addItems(["mm", "mils"])

        # Substrate combo + εr/h (auto-populated when substrate changes)
        self.cb_sub = QComboBox()
        self.cb_sub.addItem("— Custom —")
        for name in SUBSTRATES.keys():
            self.cb_sub.addItem(name)
        self.cb_sub.currentTextChanged.connect(self._on_substrate)
        self.er = QLineEdit("4.4")
        self.h = QLineEdit("1.6")

        self.base_form.addRow("Resonant freq (GHz):", self.fr)
        self.base_form.addRow("Target Z₀ (Ω):", self.z0)
        self.base_form.addRow("Substrate preset:", self.cb_sub)
        self.base_form.addRow("εr:", self.er)
        self.base_form.addRow("h — substrate (units):", self.h)
        self.base_form.addRow("Ls — margin X (units):", self.Ls)
        self.base_form.addRow("Ws — margin Y (units):", self.Ws)
        self.base_form.addRow("tan δ:", self.loss_tan)
        self.base_form.addRow("Unit:", self.cb_unit)
        v.addLayout(self.base_form)

        # Antenna-specific params (form and dict were created at top of __init__
        # because the antenna-combo signal fires during combo population)
        v.addWidget(self._h_title("Antenna-specific"))
        v.addWidget(self.extra_widget)

        # Trigger for initial extras (now that widget is in layout)
        self._antenna_changed(self.cb_ant.currentText())

        v.addStretch(1)
        self.btn_calc = QPushButton("Calculate && Generate Models")
        self.btn_calc.setMinimumHeight(40)
        self.btn_calc.clicked.connect(self.request_compute.emit)
        v.addWidget(self.btn_calc)

    def _h_title(self, t):
        lbl = QLabel(f"<b>{t}</b>")
        lbl.setStyleSheet("color: #00e0b4; padding: 6px 0;")
        return lbl

    def _populate_antennas(self, category):
        cats = available_antennas()
        self.cb_ant.blockSignals(True)
        self.cb_ant.clear()
        for name in cats.get(category, []):
            self.cb_ant.addItem(name)
        self.cb_ant.blockSignals(False)
        if self.cb_ant.count() > 0:
            self._antenna_changed(self.cb_ant.currentText())

    def _antenna_changed(self, name):
        if not name:
            return
        try:
            ant = get_antenna(name)
        except KeyError:
            return
        # Clear extra form
        for k, w in list(self._extra_inputs.items()):
            lbl = self.extra_form.labelForField(w)
            if lbl is not None:
                lbl.deleteLater()
            w.deleteLater()
        self._extra_inputs.clear()
        while self.extra_form.rowCount() > 0:
            self.extra_form.removeRow(0)
        # Populate
        for inp in ant.inputs():
            le = QLineEdit(inp.default)
            if inp.tooltip:
                le.setToolTip(inp.tooltip)
            unit_s = f" ({inp.unit})" if inp.unit else ""
            self.extra_form.addRow(inp.label + unit_s, le)
            self._extra_inputs[inp.key] = le
        if ant.notes:
            lbl = QLabel(f"<i>{ant.notes}</i>")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #a0a0a0; font-size: 11px; padding: 4px;")
            self.extra_form.addRow(lbl)
        self.antenna_changed.emit(name)

    def _on_substrate(self, name):
        if name == "— Custom —" or name not in SUBSTRATES:
            return
        s = SUBSTRATES[name]
        self.er.setText(f"{s['er']:.3f}")
        self.loss_tan.setText(f"{s['tan_d']:.4f}")
        if s["thick_mm"]:
            self.h.setText(str(s["thick_mm"][-1]))

    # ---- public API ----
    def current_antenna(self):
        return self.cb_ant.currentText()

    def read_context(self):
        """Build Context() from the current inputs."""
        unit = self.cb_unit.currentText()
        conv = 2.54e-5 if unit == "mils" else 1e-3
        out_mult = 1 / conv
        fr_hz = float(self.fr.text()) * 1e9
        er = float(self.er.text())
        z0 = float(self.z0.text())
        h = float(self.h.text()) * conv
        Ls = float(self.Ls.text()) * conv
        Ws = float(self.Ws.text()) * conv
        tan_d = float(self.loss_tan.text())
        return Context(fr=fr_hz, er=er, z0=z0, h=h, Ls=Ls, Ws=Ws,
                       loss_tangent=tan_d,
                       unit_str=unit, out_mult=out_mult)

    def read_params(self):
        """Read the antenna-specific params dict.

        Note: values with "(units)" in their label are converted to meters;
        everything else passes through as strings (antennas decide).
        """
        unit = self.cb_unit.currentText()
        conv = 2.54e-5 if unit == "mils" else 1e-3
        out = {}
        for k, w in self._extra_inputs.items():
            out[k] = w.text()
        # Let antennas that want unit conversion do it themselves; pass through raw.
        return out
