import sys
import os
import json
import csv
import subprocess
import re
import uuid
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QFormLayout, QLineEdit, QSpinBox, 
                             QDoubleSpinBox, QPushButton, QGroupBox, QLabel, 
                             QCheckBox, QMessageBox, QListWidget, QListWidgetItem, 
                             QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QSplitter)
import pyqtgraph as pg

DARK_QSS = """
QWidget { background: #242424; color: #e0e0e0; }
QGroupBox { border: 1px solid #3a3a3a; margin-top: 10px; padding-top: 10px; color: #00e0b4; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #1d1d1d; color: #e8e8e8; border: 1px solid #3a3a3a; padding: 4px; }
QPushButton { background: #00b894; color: #0a0a0a; border: none; padding: 6px; font-weight: bold; border-radius: 4px; }
QPushButton:hover { background: #00d1a8; }
QPushButton:disabled { background: #3a3a3a; color: #888; }
QLabel { color: #e0e0e0; }
QListWidget, QTableWidget { background: #1d1d1d; border: 1px solid #3a3a3a; gridline-color: #3a3a3a; }
QHeaderView::section { background: #2e2e2e; color: #e0e0e0; padding: 4px; border: 1px solid #3a3a3a; }
QTableWidget::item:selected, QListWidget::item:selected { background: #00b894; color: #0a0a0a; }
"""

class IperfWorker(QThread):
    finished = pyqtSignal(float, str)
    error = pyqtSignal(str)

    def __init__(self, ip, duration):
        super().__init__()
        self.ip = ip
        self.duration = duration

    def run(self):
        command = ["iperf3.exe", "-c", self.ip, "-t", str(self.duration), "-J"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode != 0:
                self.error.emit(f"iperf error: {result.stderr}")
                return
            data = json.loads(result.stdout)
            bps = data['end']['sum_received']['bits_per_second']
            mbps = round(bps / 1_000_000, 2)
            self.finished.emit(mbps, result.stdout)
        except Exception as e:
            self.error.emit(str(e))

class WifiTesterGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RF Throughput Tester - Engineering Build")
        self.resize(1200, 800)
        self.csv_file = "wifi_test_results.csv"
        
        self.runs = []  
        self.plot_colors = ['#00b894', '#0984e3', '#fdcb6e', '#d63031', '#6c5ce7']
        self.active_markers = [] 
        
        self.init_ui()
        self.setup_csv()
        self.load_existing_data()

    def init_ui(self):
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # --- LEFT PANEL: CONTROLS ---
        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(0,0,10,0)
        
        conn_group = QGroupBox("Target Settings")
        conn_layout = QFormLayout()
        self.ip_input = QLineEdit("192.168.0.153")
        self.duration_spin = QSpinBox()
        self.duration_spin.setValue(30)
        self.duration_spin.setRange(5, 300)
        self.duration_spin.setSuffix(" sec")
        conn_layout.addRow("Pi 4 IP:", self.ip_input)
        conn_layout.addRow("Duration:", self.duration_spin)
        conn_group.setLayout(conn_layout)
        
        param_group = QGroupBox("Test Parameters")
        param_layout = QFormLayout()
        self.antenna_input = QLineEdit("Stock Dipole")
        
        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(0, 1000)
        self.distance_spin.setValue(10.0)
        self.distance_spin.setSuffix(" ft")
        
        self.angle_spin = QSpinBox()
        self.angle_spin.setRange(0, 359)
        self.angle_spin.setSingleStep(15)
        self.angle_spin.setSuffix(" °")
        
        self.los_check = QCheckBox("Clear Line of Sight (LOS)")
        self.los_check.setChecked(True)
        
        param_layout.addRow("Antenna:", self.antenna_input)
        param_layout.addRow("Distance:", self.distance_spin)
        param_layout.addRow("Angle:", self.angle_spin)
        param_layout.addRow("", self.los_check)
        param_group.setLayout(param_layout)

        self.run_btn = QPushButton("🚀 RUN SPEED TEST")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.clicked.connect(self.start_test)
        self.status_lbl = QLabel("Ready.")

        filter_group = QGroupBox("Graph Controls")
        filter_layout = QVBoxLayout()
        
        axis_layout = QFormLayout()
        self.xaxis_combo = QComboBox()
        # Distance is now the default (Index 0)
        self.xaxis_combo.addItems(["Distance", "Angle"])
        self.xaxis_combo.currentTextChanged.connect(self.update_ui)
        axis_layout.addRow("X-Axis:", self.xaxis_combo)
        filter_layout.addLayout(axis_layout)
        
        filter_layout.addWidget(QLabel("Visible Antennas (Right-Click to Delete):"))
        self.antenna_list = QListWidget()
        self.antenna_list.itemChanged.connect(self.update_plot)
        
        # Right Click Context Menu for the Antenna List (Left Box)
        self.antenna_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.antenna_list.customContextMenuRequested.connect(self.show_antenna_context_menu)
        
        filter_layout.addWidget(self.antenna_list)
        
        self.clear_markers_btn = QPushButton("Clear Graph Markers")
        self.clear_markers_btn.clicked.connect(self.clear_markers)
        filter_layout.addWidget(self.clear_markers_btn)
        
        filter_group.setLayout(filter_layout)

        left_panel.addWidget(conn_group)
        left_panel.addWidget(param_group)
        left_panel.addWidget(self.run_btn)
        left_panel.addWidget(self.status_lbl)
        left_panel.addWidget(filter_group)

        # --- RIGHT PANEL: GRAPH AND TABLE ---
        right_panel = QVBoxLayout()
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.plot_widget = pg.PlotWidget(background='#1d1d1d')
        self.plot_widget.setLabel('left', 'Throughput', units='Mbps')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend(offset=(10, 10))
        
        # FIX: Force PanMode to prevent tiny, accidental mouse drags from causing extreme zoom-ins
        self.plot_widget.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        
        splitter.addWidget(self.plot_widget)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["ID", "Timestamp", "Antenna", "Dist (ft)", "Angle (°)", "Channel", "Signal", "Mbps"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.hideColumn(0) 
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Right-Click Context Menu for the Table Data
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        
        splitter.addWidget(self.table)
        splitter.setSizes([500, 300])
        
        right_panel.addWidget(splitter)

        main_layout.addLayout(left_panel, 1)
        main_layout.addLayout(right_panel, 3)

    def setup_csv(self):
        if not os.path.exists(self.csv_file):
            self.write_csv_headers()

    def write_csv_headers(self):
        with open(self.csv_file, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["UID", "Timestamp", "Antenna", "Distance", "Angle", "LOS", "Channel", "Signal", "Mbps"])

    def rewrite_entire_csv(self):
        self.write_csv_headers()
        with open(self.csv_file, mode='a', newline='') as f:
            writer = csv.writer(f)
            for r in self.runs:
                writer.writerow([r['uid'], r['time'], r['antenna'], r['distance'], r['angle'], r['los'], r['channel'], r['signal'], r['mbps']])

    def load_existing_data(self):
        if not os.path.exists(self.csv_file): return
        with open(self.csv_file, mode='r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    run_data = {
                        "uid": row.get("UID", str(uuid.uuid4())),
                        "time": row["Timestamp"],
                        "antenna": row["Antenna"],
                        "distance": float(row["Distance"]),
                        "angle": float(row["Angle"]),
                        "los": row.get("LOS", "Yes"),
                        "channel": row["Channel"],
                        "signal": row.get("Signal %", row.get("Signal", "Unk")),
                        "mbps": float(row["Mbps"])
                    }
                    self.runs.append(run_data)
                    self.ensure_antenna_in_list(run_data["antenna"])
                except (ValueError, KeyError):
                    continue
        self.update_ui()

    def ensure_antenna_in_list(self, antenna_name):
        for i in range(self.antenna_list.count()):
            if self.antenna_list.item(i).text() == antenna_name:
                return
        item = QListWidgetItem(antenna_name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.antenna_list.addItem(item)

    def get_windows_wifi_stats(self):
        try:
            result = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            chan_match = re.search(r"Channel\s*:\s*(\d+)", result.stdout)
            sig_match = re.search(r"Signal\s*:\s*(\d+%?)", result.stdout)
            return chan_match.group(1) if chan_match else "Unk", sig_match.group(1) if sig_match else "Unk"
        except Exception:
            return "Err", "Err"

    def start_test(self):
        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ Testing... Please wait.")
        self.worker = IperfWorker(self.ip_input.text(), self.duration_spin.value())
        self.worker.finished.connect(self.on_test_finished)
        self.worker.error.connect(self.on_test_error)
        self.worker.start()

    def on_test_finished(self, mbps, raw_json):
        channel, signal = self.get_windows_wifi_stats()
        
        run_data = {
            "uid": str(uuid.uuid4()),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "antenna": self.antenna_input.text(),
            "distance": self.distance_spin.value(),
            "angle": float(self.angle_spin.value()),
            "los": "Yes" if self.los_check.isChecked() else "No",
            "channel": channel,
            "signal": signal,
            "mbps": mbps
        }
        
        self.runs.append(run_data)
        self.rewrite_entire_csv()
        self.ensure_antenna_in_list(run_data["antenna"])
        self.update_ui()
        
        self.table.scrollToBottom() # Auto-scroll to newest
        self.status_lbl.setText(f"✅ Success: {mbps} Mbps (Ch: {channel}, Sig: {signal})")
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 RUN SPEED TEST")

    def on_test_error(self, err_msg):
        QMessageBox.critical(self, "Test Error", err_msg)
        self.status_lbl.setText("❌ Test Failed.")
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 RUN SPEED TEST")

    # --- CONTEXT MENUS ---
    def show_antenna_context_menu(self, position):
        """Right click menu for the Left Panel Antenna List."""
        item = self.antenna_list.itemAt(position)
        if not item: return
        
        menu = QMenu()
        delete_action = QAction(f"❌ Delete '{item.text()}' Traces", self)
        delete_action.triggered.connect(lambda: self.delete_entire_antenna(item.text()))
        menu.addAction(delete_action)
        menu.exec(self.antenna_list.viewport().mapToGlobal(position))

    def delete_entire_antenna(self, antenna_name):
        reply = QMessageBox.question(self, "Confirm Delete", f"Delete ALL data points for '{antenna_name}'?\nThis cannot be undone.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # Filter it out
            self.runs = [r for r in self.runs if r['antenna'] != antenna_name]
            self.rewrite_entire_csv()
            
            # Remove from list widget
            items = self.antenna_list.findItems(antenna_name, Qt.MatchFlag.MatchExactly)
            for item in items:
                self.antenna_list.takeItem(self.antenna_list.row(item))
                
            self.update_ui()
            self.status_lbl.setText(f"🗑️ Antenna '{antenna_name}' deleted.")

    def show_table_context_menu(self, position):
        """Right click menu for individual runs in the data table."""
        menu = QMenu()
        delete_action = QAction("❌ Delete Selected Run", self)
        delete_action.triggered.connect(self.delete_selected_run)
        menu.addAction(delete_action)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def delete_selected_run(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: return
        
        row = selected_rows[0].row()
        uid_to_delete = self.table.item(row, 0).text()
        
        self.runs = [r for r in self.runs if r['uid'] != uid_to_delete]
        self.rewrite_entire_csv()
        self.update_ui()
        self.status_lbl.setText("🗑️ Run deleted successfully.")

    # --- UI UPDATING ---
    def update_ui(self):
        self.refresh_table()
        self.update_plot()

    def refresh_table(self):
        self.table.setRowCount(0)
        for run in self.runs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(run['uid'])))
            self.table.setItem(row, 1, QTableWidgetItem(str(run['time'])))
            self.table.setItem(row, 2, QTableWidgetItem(str(run['antenna'])))
            self.table.setItem(row, 3, QTableWidgetItem(str(run['distance'])))
            self.table.setItem(row, 4, QTableWidgetItem(str(run['angle'])))
            self.table.setItem(row, 5, QTableWidgetItem(str(run['channel'])))
            self.table.setItem(row, 6, QTableWidgetItem(str(run['signal'])))
            
            mbps_item = QTableWidgetItem(f"{run['mbps']} Mbps")
            mbps_item.setForeground(Qt.GlobalColor.cyan)
            self.table.setItem(row, 7, mbps_item)

    def update_plot(self):
        self.plot_widget.clear()
        self.active_markers.clear()
        
        x_axis_mode = self.xaxis_combo.currentText()
        x_label = 'Distance' if x_axis_mode == "Distance" else 'Orientation Angle'
        x_units = 'ft' if x_axis_mode == "Distance" else 'Degrees'
        self.plot_widget.setLabel('bottom', x_label, units=x_units)

        visible_antennas = set()
        for i in range(self.antenna_list.count()):
            if self.antenna_list.item(i).checkState() == Qt.CheckState.Checked:
                visible_antennas.add(self.antenna_list.item(i).text())

        plot_data = {}
        for run in self.runs:
            ant = run['antenna']
            if ant in visible_antennas:
                if ant not in plot_data:
                    plot_data[ant] = {'x': [], 'y': []}
                
                x_val = run['distance'] if x_axis_mode == "Distance" else run['angle']
                plot_data[ant]['x'].append(x_val)
                plot_data[ant]['y'].append(run['mbps'])

        for i, (antenna, data) in enumerate(plot_data.items()):
            sorted_pairs = sorted(zip(data['x'], data['y']))
            x_data = [p[0] for p in sorted_pairs]
            y_data = [p[1] for p in sorted_pairs]

            color = self.plot_colors[i % len(self.plot_colors)]
            
            curve = self.plot_widget.plot(
                x_data, y_data, name=antenna, 
                pen=pg.mkPen(color=color, width=2), 
                symbol='o', symbolSize=10, symbolBrush=color, symbolPen='w' # Added white outline for clarity
            )
            
            # Reconnected the click event
            curve.sigPointsClicked.connect(self.on_graph_point_clicked)

    def on_graph_point_clicked(self, curve, points, ev=None):
        """Places a marker on the graph. Click the marker again to remove it."""
        # FIX: Accept the event so PyqtGraph doesn't try to draw a zoom box
        if ev is not None:
            ev.accept()
            
        point = points[0] 
        x = point.pos().x()
        y = point.pos().y()
        
        x_str = f"{x:.1f} ft" if self.xaxis_combo.currentText() == "Distance" else f"{x:.0f}°"
        
        # Check if we are clicking a point that already has a marker to toggle it off
        for m in self.active_markers:
            if m.pos().x() == x and m.pos().y() == y:
                self.plot_widget.removeItem(m)
                self.active_markers.remove(m)
                return

        # Format label with background to stand out
        text_label = pg.TextItem(text=f" {x_str} \n {y} Mbps ", color='#ffffff', anchor=(0.5, 1.2), fill='#00b894')
        text_label.setPos(x, y)
        
        self.plot_widget.addItem(text_label)
        self.active_markers.append(text_label)

    def clear_markers(self):
        for marker in self.active_markers:
            self.plot_widget.removeItem(marker)
        self.active_markers.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    window = WifiTesterGUI()
    window.show()
    sys.exit(app.exec())