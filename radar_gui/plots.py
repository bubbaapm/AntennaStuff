"""PyQtGraph plot widgets for radar, VNA verification, DSP, and replay."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import RadarFrame, SweepFrame


def configure_plot(plot: pg.PlotItem, title: str, x_label: str, y_label: str) -> None:
    plot.setTitle(title)
    plot.setLabel("bottom", x_label)
    plot.setLabel("left", y_label)
    plot.showGrid(x=True, y=True, alpha=0.25)


class RadarView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.scale_label = QLabel("A-scope Y max: --")
        self.scale_label.setStyleSheet("color:#b8d7ff; padding: 2px 4px;")
        layout.addWidget(self.scale_label)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.ascope = pg.PlotWidget()
        configure_plot(self.ascope.getPlotItem(), "A-Scope", "Distance (m)", "Magnitude")
        self.ascope_curve = self.ascope.plot(pen=pg.mkPen("#00e0b4", width=2))
        self.peak_scatter = pg.ScatterPlotItem(size=10, brush=pg.mkBrush("#ffcf5a"))
        self.ascope.addItem(self.peak_scatter)
        self.waterfall = pg.PlotWidget()
        configure_plot(self.waterfall.getPlotItem(), "Waterfall", "Distance (m)", "Sweep history")
        self.waterfall_img = pg.ImageItem()
        self.waterfall.addItem(self.waterfall_img)
        splitter.addWidget(self.ascope)
        splitter.addWidget(self.waterfall)
        splitter.setSizes([520, 360])
        bottom = QSplitter(Qt.Orientation.Horizontal)
        self.peak_table = QTableWidget(0, 3)
        self.peak_table.setHorizontalHeaderLabels(["Distance (m)", "Amplitude", "Prominence"])
        self.peak_history = pg.PlotWidget()
        configure_plot(self.peak_history.getPlotItem(), "Peak History", "Sweep", "Distance (m)")
        self.peak_history_curve = self.peak_history.plot(pen=pg.mkPen("#ffcf5a", width=2))
        bottom.addWidget(self.peak_table)
        bottom.addWidget(self.peak_history)
        bottom.setSizes([300, 700])
        layout.addWidget(splitter, 4)
        layout.addWidget(bottom, 1)
        self._waterfall_rows: list[np.ndarray] = []
        self._waterfall_bin_count = 0
        self._peak_distances: list[float] = []
        self._ascope_ymax = 1e-3

    def update_radar(self, frame: RadarFrame) -> None:
        self.ascope_curve.setData(frame.distance_m, frame.magnitude)
        self._update_ascope_scale(frame.magnitude)
        self.peak_scatter.setData(
            [p.distance_m for p in frame.peaks],
            [p.amplitude for p in frame.peaks],
        )
        self._update_peak_table(frame)
        if frame.waterfall_row.size:
            if self._waterfall_bin_count != int(frame.waterfall_row.size):
                self._waterfall_rows = []
                self._waterfall_bin_count = int(frame.waterfall_row.size)
            self._waterfall_rows.append(frame.waterfall_row)
            self._waterfall_rows = self._waterfall_rows[-250:]
            image = np.vstack(self._waterfall_rows)
            self.waterfall_img.setImage(image.T, autoLevels=False, levels=(0.0, 1.0))
            if frame.distance_m.size > 1:
                width = float(frame.distance_m[-1] - frame.distance_m[0])
                self.waterfall_img.setRect(float(frame.distance_m[0]), 0.0, width, float(len(self._waterfall_rows)))
        if frame.peaks:
            self._peak_distances.append(frame.peaks[0].distance_m)
            self._peak_distances = self._peak_distances[-500:]
            self.peak_history_curve.setData(np.arange(len(self._peak_distances)), self._peak_distances)

    def clear_history(self) -> None:
        self._waterfall_rows = []
        self._waterfall_bin_count = 0
        self._peak_distances = []
        self.peak_history_curve.setData([], [])

    def _update_ascope_scale(self, magnitude: np.ndarray) -> None:
        if magnitude.size == 0:
            return
        measured = float(np.nanmax(magnitude))
        floor = 1e-3
        target = max(floor, measured * 1.25)
        if target > self._ascope_ymax:
            self._ascope_ymax = target
        elif target < self._ascope_ymax * 0.45:
            self._ascope_ymax = max(floor, self._ascope_ymax * 0.96)
        self.ascope.setYRange(0.0, self._ascope_ymax, padding=0.0)
        self.scale_label.setText(
            f"A-scope Y max: {self._format_eng(self._ascope_ymax)}  |  peak: {self._format_eng(measured)}"
        )

    @staticmethod
    def _format_eng(value: float) -> str:
        if value == 0 or not np.isfinite(value):
            return "0"
        prefixes = ((1e-9, "n"), (1e-6, "u"), (1e-3, "m"), (1.0, ""), (1e3, "k"), (1e6, "M"))
        scale, suffix = prefixes[3]
        for candidate, label in prefixes:
            if abs(value) >= candidate:
                scale, suffix = candidate, label
        return f"{value / scale:.3g} {suffix}".strip()

    def _update_peak_table(self, frame: RadarFrame) -> None:
        self.peak_table.setRowCount(len(frame.peaks))
        for row, peak in enumerate(frame.peaks):
            values = [peak.distance_m, peak.amplitude, peak.prominence]
            for col, value in enumerate(values):
                self.peak_table.setItem(row, col, QTableWidgetItem(f"{value:.6g}"))


class VnaVerifyView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.mag = pg.PlotWidget()
        configure_plot(self.mag.getPlotItem(), "S11 / S21 Magnitude", "Frequency (GHz)", "dB")
        self.s11_mag = self.mag.plot(pen=pg.mkPen("#ff7675", width=2), name="S11")
        self.s21_mag = self.mag.plot(pen=pg.mkPen("#00e0b4", width=2), name="S21")
        self.phase = pg.PlotWidget()
        configure_plot(self.phase.getPlotItem(), "S11 / S21 Phase", "Frequency (GHz)", "Degrees")
        self.s11_phase = self.phase.plot(pen=pg.mkPen("#ff7675", width=2))
        self.s21_phase = self.phase.plot(pen=pg.mkPen("#00e0b4", width=2))
        self.smith = pg.PlotWidget()
        configure_plot(self.smith.getPlotItem(), "S11 Smith-ish View", "Real(Gamma)", "Imag(Gamma)")
        self.smith.setXRange(-1.2, 1.2)
        self.smith.setYRange(-1.2, 1.2)
        self.smith_curve = self.smith.plot(pen=pg.mkPen("#ff7675", width=2))
        splitter.addWidget(self.mag)
        splitter.addWidget(self.phase)
        splitter.addWidget(self.smith)
        layout.addWidget(splitter)

    def update_sweep(self, frame: SweepFrame) -> None:
        freq_ghz = frame.freq_hz / 1e9
        s21_db = 20.0 * np.log10(np.maximum(np.abs(frame.s21), 1e-15))
        self.s21_mag.setData(freq_ghz, s21_db)
        self.s21_phase.setData(freq_ghz, np.unwrap(np.angle(frame.s21)) * 180.0 / np.pi)
        if frame.s11 is not None:
            s11_db = 20.0 * np.log10(np.maximum(np.abs(frame.s11), 1e-15))
            self.s11_mag.setData(freq_ghz, s11_db)
            self.s11_phase.setData(freq_ghz, np.unwrap(np.angle(frame.s11)) * 180.0 / np.pi)
            self.smith_curve.setData(frame.s11.real, frame.s11.imag)


class DspInspectorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        grid = QSplitter(Qt.Orientation.Vertical)
        self.raw = pg.PlotWidget()
        configure_plot(self.raw.getPlotItem(), "Raw / Background S21", "Point", "Magnitude")
        self.raw_curve = self.raw.plot(pen=pg.mkPen("#00e0b4", width=2))
        self.bg_curve = self.raw.plot(pen=pg.mkPen("#777", width=1))
        self.sub = pg.PlotWidget()
        configure_plot(self.sub.getPlotItem(), "Subtracted / EMA", "Point", "Magnitude")
        self.sub_curve = self.sub.plot(pen=pg.mkPen("#74b9ff", width=2))
        self.ema_curve = self.sub.plot(pen=pg.mkPen("#ffcf5a", width=2))
        self.windowed = pg.PlotWidget()
        configure_plot(self.windowed.getPlotItem(), "Windowed Frequency Trace", "Point", "Magnitude")
        self.windowed_curve = self.windowed.plot(pen=pg.mkPen("#a29bfe", width=2))
        self.range = pg.PlotWidget()
        configure_plot(self.range.getPlotItem(), "Processed Range Output", "Distance (m)", "Magnitude")
        self.range_curve = self.range.plot(pen=pg.mkPen("#00e0b4", width=2))
        for widget in (self.raw, self.sub, self.windowed, self.range):
            grid.addWidget(widget)
        layout.addWidget(grid)

    def update_inspector(self, frame: RadarFrame) -> None:
        i = frame.intermediates
        if not i:
            return
        x = np.arange(i["raw_s21"].size)
        self.raw_curve.setData(x, np.abs(i["raw_s21"]))
        self.sub_curve.setData(x, np.abs(i["subtracted"]))
        self.ema_curve.setData(x, np.abs(i["ema"]))
        self.windowed_curve.setData(x, np.abs(i["windowed"]))
        self.range_curve.setData(frame.distance_m, frame.magnitude)

    def set_background(self, background: np.ndarray | None) -> None:
        if background is None:
            self.bg_curve.setData([], [])
        else:
            self.bg_curve.setData(np.arange(background.size), np.abs(background))


class ReplayView(QWidget):
    frame_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.btn_stop = QPushButton("Stop")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.label = QLabel("No replay loaded")
        top.addWidget(self.btn_play)
        top.addWidget(self.btn_stop)
        top.addWidget(self.slider, 1)
        top.addWidget(self.label)
        layout.addLayout(top)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._advance)
        self.btn_play.clicked.connect(self.timer.start)
        self.btn_stop.clicked.connect(self.timer.stop)
        self.slider.valueChanged.connect(self._selected)

    def set_count(self, count: int) -> None:
        self.slider.setRange(0, max(0, count - 1))
        self.label.setText(f"{count} replay frames" if count else "No replay loaded")

    def _selected(self, idx: int) -> None:
        self.frame_selected.emit(idx)

    def _advance(self) -> None:
        if self.slider.maximum() <= 0:
            return
        next_idx = self.slider.value() + 1
        if next_idx > self.slider.maximum():
            next_idx = 0
        self.slider.setValue(next_idx)
