"""Small PyQt front-end for LibreVNA characterization runs."""
from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import List

from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtGui import QAction, QFont, QKeySequence, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..scpi import ScpiClient, ScpiError
from .characterize import default_run_dir


APP_ROOT = Path(__file__).resolve().parents[2]


class CharacterizationWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LibreVNA Characterization Tool")
        self.resize(980, 760)
        self._process: QProcess | None = None
        self._last_run_dir: Path | None = None
        self._mode = ""
        self._auto_out_dir = True
        self._last_auto_out_dir = ""

        self._build_ui()
        self._build_toolbar()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready.")

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        tabs = QTabWidget()
        tabs.addTab(self._build_run_tab(), "Run")
        tabs.addTab(self._build_analysis_tab(), "Analyze")
        layout.addWidget(tabs, 1)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(220)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.console.setFont(mono)
        layout.addWidget(self.console)

        self.setCentralWidget(root)

    def _build_run_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(6, 8, 6, 6)
        outer.setSpacing(8)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        grid.addWidget(self._connection_box(), 0, 0)
        grid.addWidget(self._dut_box(), 0, 1)
        grid.addWidget(self._sweep_box(), 1, 0)
        grid.addWidget(self._schedule_box(), 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addWidget(grid_host)

        out_box = QGroupBox("Output")
        out_layout = QFormLayout(out_box)
        row = QHBoxLayout()
        self.out_dir = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_out_dir)
        row.addWidget(self.out_dir, 1)
        row.addWidget(browse)
        out_layout.addRow("Run folder:", row)
        outer.addWidget(out_box)

        cmd_box = QGroupBox("Command Preview")
        cmd_layout = QVBoxLayout(cmd_box)
        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumHeight(92)
        self.command_preview.setFont(QFont("Consolas", 9))
        cmd_layout.addWidget(self.command_preview)
        outer.addWidget(cmd_box)

        actions = QHBoxLayout()
        self.btn_start = QPushButton("Start Run")
        self.btn_stop = QPushButton("Stop")
        self.btn_read_vna = QPushButton("Read From VNA")
        self.btn_refresh = QPushButton("Refresh Preview")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self._start_run)
        self.btn_stop.clicked.connect(self._stop_process)
        self.btn_read_vna.clicked.connect(self._read_sweep_from_vna)
        self.btn_refresh.clicked.connect(self._refresh_preview)
        actions.addStretch(1)
        actions.addWidget(self.btn_read_vna)
        actions.addWidget(self.btn_refresh)
        actions.addWidget(self.btn_stop)
        actions.addWidget(self.btn_start)
        outer.addLayout(actions)

        for widget in self._preview_sources():
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._refresh_preview)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._refresh_preview)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self._refresh_preview)
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self._refresh_preview)
        self.dut.textChanged.connect(self._update_default_out_dir)
        self.out_dir.textEdited.connect(self._mark_out_dir_manual)
        self._update_default_out_dir()
        self._refresh_preview()
        return page

    def _connection_box(self) -> QGroupBox:
        box = QGroupBox("Connection")
        form = QFormLayout(box)
        self.host = QLineEdit("localhost")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(19542)
        self.librevna_gui = QLineEdit()
        self.librevna_gui.setPlaceholderText("Optional path to LibreVNA-GUI")
        self.librevna_gui.setToolTip("If set, the runner starts LibreVNA-GUI when SCPI is not already reachable.")
        gui_row = QHBoxLayout()
        gui_browse = QPushButton("Browse...")
        gui_browse.clicked.connect(self._browse_librevna_gui)
        gui_row.addWidget(self.librevna_gui, 1)
        gui_row.addWidget(gui_browse)
        self.show_librevna_gui = QCheckBox("Show window")
        self.show_librevna_gui.setToolTip("Off starts LibreVNA-GUI with --no-gui. On leaves the window visible.")
        self.keep_librevna_gui = QCheckBox("Keep running after test")
        self.keep_librevna_gui.setToolTip("Leave LibreVNA-GUI running when this tool started it.")
        form.addRow("SCPI host:", self.host)
        form.addRow("SCPI port:", self.port)
        form.addRow("LibreVNA-GUI:", gui_row)
        form.addRow("", self.show_librevna_gui)
        form.addRow("", self.keep_librevna_gui)
        return box

    def _dut_box(self) -> QGroupBox:
        box = QGroupBox("DUT")
        form = QFormLayout(box)
        self.dut = QLineEdit("50 ohm load dry run")
        self.kind = QComboBox()
        self.kind.addItems(["antenna", "load", "open", "short", "thru", "cable", "other"])
        self.kind.setCurrentText("load")
        self.notes = QLineEdit()
        self.calibration = QLineEdit()
        self.calibration.setPlaceholderText("Optional .cal path, or latest")
        cal_row = QHBoxLayout()
        cal_browse = QPushButton("Browse...")
        cal_browse.clicked.connect(self._browse_calibration)
        cal_row.addWidget(self.calibration, 1)
        cal_row.addWidget(cal_browse)
        form.addRow("Name:", self.dut)
        form.addRow("Kind:", self.kind)
        form.addRow("Notes:", self.notes)
        form.addRow("Cal file:", cal_row)
        self.use_cal_sweep = QCheckBox("Use cal sweep")
        self.use_cal_sweep.setToolTip("After loading calibration, use the active/calibration sweep grid instead of the Start/Stop/Points fields.")
        form.addRow("", self.use_cal_sweep)
        return box

    def _sweep_box(self) -> QGroupBox:
        box = QGroupBox("Sweep")
        form = QFormLayout(box)
        self.start_hz = QLineEdit("2.3e9")
        self.stop_hz = QLineEdit("2.6e9")
        self.points = QSpinBox()
        self.points.setRange(2, 100001)
        self.points.setValue(1001)
        self.ifbw_hz = QLineEdit("1000")
        self.averaging = QSpinBox()
        self.averaging.setRange(1, 10000)
        self.averaging.setValue(4)
        self.power_dbm = QLineEdit("-10")
        self.full_2port = QCheckBox("Save full 2-port .s2p")
        self.full_2port.setToolTip(
            "Off: save only S11 as one .s1p per sweep, best for antennas. "
            "On: save S11/S21/S12/S22 together as one .s2p per sweep, best for thru/cable tests."
        )
        form.addRow("Start Hz:", self.start_hz)
        form.addRow("Stop Hz:", self.stop_hz)
        form.addRow("Points:", self.points)
        form.addRow("IFBW Hz:", self.ifbw_hz)
        form.addRow("Averaging:", self.averaging)
        form.addRow("Power dBm:", self.power_dbm)
        form.addRow("Traces:", self.full_2port)
        return box

    def _schedule_box(self) -> QGroupBox:
        box = QGroupBox("Schedule")
        form = QFormLayout(box)
        self.interval_s = QSpinBox()
        self.interval_s.setRange(0, 604800)
        self.interval_s.setValue(30)
        self.interval_s.setToolTip("Seconds between the start of one saved sweep and the start of the next.")
        self.count = QSpinBox()
        self.count.setRange(0, 1000000)
        self.count.setValue(10)
        self.count.setToolTip("Number of saved sweeps. If this is greater than zero, it takes priority over Duration.")
        self.duration_s = QSpinBox()
        self.duration_s.setRange(0, 31536000)
        self.duration_s.setValue(0)
        self.duration_s.setToolTip("Total run time in seconds. Used only when Count is set to 0.")
        self.timeout_s = QSpinBox()
        self.timeout_s.setRange(1, 3600)
        self.timeout_s.setValue(120)
        self.timeout_s.setToolTip("Maximum time to wait for one sweep to finish before treating it as failed.")
        self.target_db = QLineEdit("-10")
        self.target_db.setToolTip("Analysis threshold for return-loss bandwidth. It does not change the VNA measurement.")
        form.addRow("Interval s:", self.interval_s)
        form.addRow("Count:", self.count)
        form.addRow("Duration s:", self.duration_s)
        form.addRow("Sweep timeout s:", self.timeout_s)
        form.addRow("Bandwidth target dB:", self.target_db)
        return box

    def _build_analysis_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(6, 8, 6, 6)
        outer.setSpacing(8)

        box = QGroupBox("Analyze Existing Run")
        form = QFormLayout(box)
        run_row = QHBoxLayout()
        self.analysis_run_dir = QLineEdit()
        run_browse = QPushButton("Browse...")
        run_browse.clicked.connect(self._browse_analysis_dir)
        run_row.addWidget(self.analysis_run_dir, 1)
        run_row.addWidget(run_browse)
        out_row = QHBoxLayout()
        self.analysis_out_dir = QLineEdit()
        out_browse = QPushButton("Browse...")
        out_browse.clicked.connect(self._browse_analysis_out_dir)
        out_row.addWidget(self.analysis_out_dir, 1)
        out_row.addWidget(out_browse)
        form.addRow("Run folder:", run_row)
        form.addRow("Output folder:", out_row)
        outer.addWidget(box)

        help_text = QLabel(
            "The analyzer reads summary.csv and raw Touchstone files, then writes PNG plots "
            "and analysis_report.md."
        )
        help_text.setWordWrap(True)
        outer.addWidget(help_text)

        actions = QHBoxLayout()
        self.btn_analyze_last = QPushButton("Use Last Run")
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze_last.clicked.connect(self._use_last_run_for_analysis)
        self.btn_analyze.clicked.connect(self._start_analysis)
        actions.addStretch(1)
        actions.addWidget(self.btn_analyze_last)
        actions.addWidget(self.btn_analyze)
        outer.addLayout(actions)
        outer.addStretch(1)
        return page

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Actions", self)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        start = QAction("Start", self)
        start.setShortcut(QKeySequence("F5"))
        start.triggered.connect(self._start_run)
        stop = QAction("Stop", self)
        stop.setShortcut(QKeySequence("Esc"))
        stop.triggered.connect(self._stop_process)
        read_vna = QAction("Read VNA", self)
        read_vna.triggered.connect(self._read_sweep_from_vna)
        analyze = QAction("Analyze", self)
        analyze.setShortcut(QKeySequence("F6"))
        analyze.triggered.connect(self._start_analysis)
        toolbar.addAction(start)
        toolbar.addAction(stop)
        toolbar.addAction(read_vna)
        toolbar.addAction(analyze)

    def _preview_sources(self) -> List[QWidget]:
        return [
            self.host,
            self.port,
            self.librevna_gui,
            self.show_librevna_gui,
            self.keep_librevna_gui,
            self.dut,
            self.kind,
            self.notes,
            self.calibration,
            self.use_cal_sweep,
            self.start_hz,
            self.stop_hz,
            self.points,
            self.ifbw_hz,
            self.averaging,
            self.power_dbm,
            self.full_2port,
            self.interval_s,
            self.count,
            self.duration_s,
            self.timeout_s,
            self.target_db,
            self.out_dir,
        ]

    def _mark_out_dir_manual(self) -> None:
        if self.out_dir.text() != self._last_auto_out_dir:
            self._auto_out_dir = False

    def _update_default_out_dir(self) -> None:
        if not self._auto_out_dir:
            return
        path = str(default_run_dir(self.dut.text().strip() or "DUT"))
        self._last_auto_out_dir = path
        self.out_dir.setText(path)

    def _browse_out_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose run folder", self.out_dir.text())
        if path:
            self._auto_out_dir = False
            self.out_dir.setText(path)

    def _browse_calibration(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose calibration file", str(APP_ROOT / "cals"), "Calibration (*.cal);;All files (*)")
        if path:
            self.calibration.setText(path)

    def _browse_librevna_gui(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose LibreVNA-GUI executable",
            str(Path.home()),
            "LibreVNA-GUI (LibreVNA-GUI LibreVNA-GUI.exe);;All files (*)",
        )
        if path:
            self.librevna_gui.setText(path)

    def _browse_analysis_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose run folder", self.analysis_run_dir.text() or str(APP_ROOT))
        if path:
            self.analysis_run_dir.setText(path)
            if not self.analysis_out_dir.text().strip():
                self.analysis_out_dir.setText(str(Path(path) / "analysis"))

    def _browse_analysis_out_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose analysis output folder", self.analysis_out_dir.text() or str(APP_ROOT))
        if path:
            self.analysis_out_dir.setText(path)

    def _logger_args(self) -> List[str]:
        traces = "S11,S21,S12,S22" if self.full_2port.isChecked() else "S11"
        args = [
            "-m",
            "vna_tester.tools.characterize",
            "--host",
            self.host.text().strip() or "localhost",
            "--port",
            str(self.port.value()),
        ]
        if self.librevna_gui.text().strip():
            args.extend(["--librevna-gui", self.librevna_gui.text().strip()])
        if self.show_librevna_gui.isChecked():
            args.append("--show-librevna-gui")
        if self.keep_librevna_gui.isChecked():
            args.append("--keep-librevna-gui")
        if self.use_cal_sweep.isChecked():
            args.append("--use-cal-sweep")
        args.extend([
            "--dut",
            self.dut.text().strip() or "DUT",
            "--kind",
            self.kind.currentText(),
            "--out",
            self.out_dir.text().strip(),
            "--start",
            self.start_hz.text().strip(),
            "--stop",
            self.stop_hz.text().strip(),
            "--points",
            str(self.points.value()),
            "--ifbw",
            self.ifbw_hz.text().strip(),
            "--averaging",
            str(self.averaging.value()),
            "--power",
            self.power_dbm.text().strip(),
            "--traces",
            traces,
            "--interval",
            str(self.interval_s.value()),
            "--timeout",
            str(self.timeout_s.value()),
            "--target-db",
            self.target_db.text().strip(),
        ])
        if self.count.value() > 0:
            args.extend(["--count", str(self.count.value())])
        else:
            args.extend(["--duration", str(self.duration_s.value())])
        if self.notes.text().strip():
            args.extend(["--notes", self.notes.text().strip()])
        if self.calibration.text().strip():
            args.extend(["--calibration", self.calibration.text().strip()])
        return args

    def _analysis_args(self) -> List[str]:
        args = ["-m", "vna_tester.tools.analyze_characterization", self.analysis_run_dir.text().strip()]
        if self.analysis_out_dir.text().strip():
            args.extend(["--out", self.analysis_out_dir.text().strip()])
        return args

    def _refresh_preview(self) -> None:
        try:
            parts = [sys.executable] + self._logger_args()
            self.command_preview.setPlainText(" ".join(shlex.quote(part) for part in parts))
        except RuntimeError:
            pass

    def _read_sweep_from_vna(self) -> None:
        if self._process is not None:
            QMessageBox.information(self, "Process running", "Stop the current process first.")
            return
        client = ScpiClient(self.host.text().strip() or "localhost", self.port.value(), timeout=5.0)
        try:
            client.connect()
            self.start_hz.setText(client.query(":VNA:FREQ:START?").strip())
            self.stop_hz.setText(client.query(":VNA:FREQ:STOP?").strip())
            self.points.setValue(int(float(client.query(":VNA:ACQ:POINTS?").strip())))
            self.ifbw_hz.setText(client.query(":VNA:ACQ:IFBW?").strip())
            self.averaging.setValue(max(1, int(float(client.query(":VNA:ACQ:AVG?").strip()))))
            self.power_dbm.setText(client.query(":VNA:STIM:LVL?").strip())
            self.statusBar().showMessage("Copied active VNA sweep settings.")
        except (OSError, ValueError, ScpiError) as exc:
            QMessageBox.warning(self, "Read failed", str(exc))
        finally:
            client.close()

    def _start_run(self) -> None:
        if self._process is not None:
            QMessageBox.information(self, "Process running", "Stop the current process first.")
            return
        if not self.out_dir.text().strip():
            QMessageBox.warning(self, "Missing output", "Choose an output folder.")
            return
        out = Path(self.out_dir.text().strip())
        self._last_run_dir = out
        self.analysis_run_dir.setText(str(out))
        self.analysis_out_dir.setText(str(out / "analysis"))
        self._mode = "run"
        self._start_process(self._logger_args())

    def _start_analysis(self) -> None:
        if self._process is not None:
            QMessageBox.information(self, "Process running", "Stop the current process first.")
            return
        if not self.analysis_run_dir.text().strip():
            self._use_last_run_for_analysis()
        if not self.analysis_run_dir.text().strip():
            QMessageBox.warning(self, "Missing run folder", "Choose a run folder containing summary.csv.")
            return
        self._mode = "analysis"
        self._start_process(self._analysis_args())

    def _start_process(self, args: List[str]) -> None:
        self.console.appendPlainText("> " + " ".join(shlex.quote(part) for part in [sys.executable] + args))
        proc = QProcess(self)
        proc.setWorkingDirectory(str(APP_ROOT))
        proc.setProgram(sys.executable)
        proc.setArguments(args)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(self._read_process_output)
        proc.finished.connect(self._process_finished)
        proc.errorOccurred.connect(self._process_error)
        self._process = proc
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_analyze.setEnabled(False)
        self.statusBar().showMessage("Running...")
        proc.start()

    def _read_process_output(self) -> None:
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text:
            self.console.moveCursor(QTextCursor.MoveOperation.End)
            self.console.insertPlainText(text)
            self.console.moveCursor(QTextCursor.MoveOperation.End)

    def _process_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        mode = self._mode
        self._read_process_output()
        self.console.appendPlainText(f"\nProcess finished with exit code {exit_code}.\n")
        self._process = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_analyze.setEnabled(True)
        if mode == "run" and exit_code == 0 and self._last_run_dir is not None:
            self.analysis_run_dir.setText(str(self._last_run_dir))
            self.analysis_out_dir.setText(str(self._last_run_dir / "analysis"))
            self.statusBar().showMessage("Run complete. Ready to analyze.")
        elif mode == "analysis" and exit_code == 0:
            self.statusBar().showMessage("Analysis complete.")
        else:
            self.statusBar().showMessage("Process stopped or failed.")

    def _process_error(self, error: QProcess.ProcessError) -> None:
        self.console.appendPlainText(f"\nProcess error: {error.name}\n")

    def _stop_process(self) -> None:
        if self._process is None:
            return
        self.console.appendPlainText("\nStopping process...\n")
        self._process.terminate()
        if not self._process.waitForFinished(2500):
            self._process.kill()

    def _use_last_run_for_analysis(self) -> None:
        if self._last_run_dir is not None:
            self.analysis_run_dir.setText(str(self._last_run_dir))
            self.analysis_out_dir.setText(str(self._last_run_dir / "analysis"))


def main() -> int:
    app = QApplication(sys.argv)
    win = CharacterizationWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
