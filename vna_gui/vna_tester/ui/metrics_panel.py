"""
Antenna metrics readout panel — auto-computes figures of merit from S11/S22.
"""
from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..metrics import antenna_metrics, format_freq, format_z
from ..trace import TraceManager


class MetricsPanel(QGroupBox):
    """Reads from a TraceManager; auto-updates whenever traces change."""

    def __init__(self, traces: TraceManager, parent=None):
        super().__init__("Antenna metrics", parent)
        self.traces = traces
        self._z0 = 50.0
        self._target_db = -10.0
        self._build()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)  # metrics are cheap, but no need >8 Hz
        self._timer.timeout.connect(self._refresh_values)

        traces.traces_changed.connect(self._refresh_set)
        traces.traces_data.connect(self._timer.start)
        self._refresh()

    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 12, 8, 8)
        v.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(QLabel("Trace:"))
        self.cb_trace = QComboBox()
        self.cb_trace.setToolTip(
            "Which trace to compute metrics from. Antenna 1 → S11, antenna 2 → S22."
        )
        self.cb_trace.currentTextChanged.connect(lambda _: self._refresh())
        top.addWidget(self.cb_trace, 1)
        v.addLayout(top)

        f = QFormLayout()
        f.setHorizontalSpacing(8)
        f.setVerticalSpacing(4)
        self.lbl_fres = QLabel("—")
        self.lbl_s11min = QLabel("—")
        self.lbl_vswr = QLabel("—")
        self.lbl_band = QLabel("—")
        self.lbl_bw = QLabel("—")
        self.lbl_fbw = QLabel("—")
        self.lbl_z = QLabel("—")
        self.lbl_q = QLabel("—")
        self.lbl_pass = QLabel("—")
        self.lbl_mismatch = QLabel("—")
        big = QFont(); big.setPointSize(10); big.setBold(True)
        self.lbl_pass.setFont(big)
        # Size policy "Ignored" so labels never demand more width than the
        # panel can give. Word wrap covers vertical growth instead.
        for lbl in (self.lbl_fres, self.lbl_s11min, self.lbl_vswr,
                    self.lbl_band, self.lbl_bw, self.lbl_fbw,
                    self.lbl_z, self.lbl_q, self.lbl_mismatch, self.lbl_pass):
            lbl.setStyleSheet("color:#e0e0e0;")
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Ignored,
                              QSizePolicy.Policy.Preferred)
            lbl.setMinimumWidth(0)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        f.addRow("f₀:", self.lbl_fres)
        f.addRow("S₁₁ min:", self.lbl_s11min)
        f.addRow("VSWR:", self.lbl_vswr)
        f.addRow("Band:", self.lbl_band)
        f.addRow("BW:", self.lbl_bw)
        f.addRow("Frac BW:", self.lbl_fbw)
        f.addRow("Z:", self.lbl_z)
        f.addRow("Q:", self.lbl_q)
        f.addRow("M.loss:", self.lbl_mismatch)
        f.addRow("Verdict:", self.lbl_pass)
        v.addLayout(f)
        self.setToolTip(
            "Metrics computed host-side from the selected trace.\n"
            "Verdict ✓ means S₁₁ at the resonance dip is below the marker-panel target."
        )

    def set_z0(self, z0: float) -> None:
        self._z0 = float(z0)
        self._refresh()

    def set_target_db(self, target_db: float) -> None:
        self._target_db = float(target_db)
        self._refresh()

    def _refresh(self) -> None:
        """Combo + values; used on user actions or initial paint."""
        self._refresh_trace_combo()
        self._refresh_values()

    def _refresh_set(self) -> None:
        self._refresh_trace_combo()
        self._timer.start()

    def _refresh_values(self) -> None:
        name = self.cb_trace.currentText().strip()
        tr = self.traces.get(name) if name else None
        if tr is None or tr.freq.size == 0:
            for lbl in (self.lbl_fres, self.lbl_s11min, self.lbl_vswr,
                        self.lbl_band, self.lbl_bw, self.lbl_fbw,
                        self.lbl_z, self.lbl_q, self.lbl_mismatch,
                        self.lbl_pass):
                lbl.setText("—")
                lbl.setStyleSheet("color:#888;")
            return

        m = antenna_metrics(tr, z0=self._z0, target_db=self._target_db)
        self.lbl_fres.setText(format_freq(m.f_resonance_hz))
        self.lbl_s11min.setText(f"{m.s11_min_db:.2f} dB")
        self.lbl_vswr.setText(f"{m.vswr_at_resonance:.2f} : 1")
        if m.f_low_m10db_hz is not None and m.f_high_m10db_hz is not None and m.bandwidth_m10db_hz > 0:
            self.lbl_band.setText(
                f"{format_freq(m.f_low_m10db_hz)} … {format_freq(m.f_high_m10db_hz)}"
            )
            self.lbl_bw.setText(format_freq(m.bandwidth_m10db_hz))
        else:
            self.lbl_band.setText("(none)")
            self.lbl_bw.setText("—")
        self.lbl_fbw.setText(f"{m.fractional_bw_pct:.2f} %" if m.fractional_bw_pct else "—")
        self.lbl_z.setText(format_z(m.impedance_at_resonance))
        self.lbl_q.setText(f"{m.quality_factor:.1f}" if m.quality_factor else "—")
        self.lbl_mismatch.setText(f"{m.mismatch_loss_db:.2f} dB")

        if m.s11_min_db <= self._target_db:
            self.lbl_pass.setText("✓ pass")
            self.lbl_pass.setToolTip(
                f"Resonance at {format_freq(m.f_resonance_hz)} reaches "
                f"{m.s11_min_db:.2f} dB, which is below the target of "
                f"{self._target_db:.1f} dB."
            )
            self.lbl_pass.setStyleSheet("color:#00e0b4;")
        else:
            self.lbl_pass.setText(f"✗ fail ({m.s11_min_db:.1f} > {self._target_db:.0f} dB)")
            self.lbl_pass.setToolTip(
                f"Best return loss across the sweep is {m.s11_min_db:.2f} dB, "
                f"which does not reach the target of {self._target_db:.1f} dB. "
                f"Adjust the target in the Markers panel if needed."
            )
            self.lbl_pass.setStyleSheet("color:#ff5252;")

    def _refresh_trace_combo(self) -> None:
        self.cb_trace.blockSignals(True)
        prev = self.cb_trace.currentText()
        self.cb_trace.clear()
        # Show S11/S22 first, then everything else
        names = [t.name for t in self.traces.live() if t.parameter in ("S11", "S22")]
        names += [t.name for t in self.traces.live() if t.parameter not in ("S11", "S22")]
        names += [t.name for t in self.traces.references()]
        seen = set()
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            self.cb_trace.addItem(n)
        if prev and prev in seen:
            self.cb_trace.setCurrentText(prev)
        elif "S11" in seen:
            self.cb_trace.setCurrentText("S11")
        self.cb_trace.blockSignals(False)
