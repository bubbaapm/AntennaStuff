"""
3D radiation pattern viewer (pyqtgraph OpenGL).

A QWidget that takes (theta, phi, U) arrays and renders an interactive 3D surface.
"""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, \
    QLabel, QSlider, QComboBox
from PyQt6.QtCore import Qt
import matplotlib as mpl


class Radiation3DView(QWidget):
    """Interactive 3D far-field pattern."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._pattern_fn = None
        self._ctx = None
        self._results = None

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        # Controls
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("Scale:"))
        self.cb_log = QComboBox()
        self.cb_log.addItems(["Linear", "dB (−30 dB floor)", "dB (−40 dB floor)"])
        self.cb_log.currentIndexChanged.connect(self._update_plot)
        ctl.addWidget(self.cb_log)
        ctl.addWidget(QLabel("Resolution:"))
        self.sl_res = QSlider(Qt.Orientation.Horizontal)
        self.sl_res.setRange(30, 120); self.sl_res.setValue(72)
        self.sl_res.setFixedWidth(140)
        self.sl_res.sliderReleased.connect(self._update_plot)
        ctl.addWidget(self.sl_res)
        self.chk_grid = QCheckBox("Grid")
        self.chk_grid.setChecked(True)
        self.chk_grid.stateChanged.connect(self._toggle_grid)
        ctl.addWidget(self.chk_grid)
        self.chk_wire = QCheckBox("Wireframe")
        self.chk_wire.stateChanged.connect(self._update_plot)
        ctl.addWidget(self.chk_wire)
        self.chk_show_geom = QCheckBox("Show antenna")
        self.chk_show_geom.setChecked(True)
        self.chk_show_geom.setToolTip(
            "Draw a translucent outline of the antenna's PCB board at z=0 "
            "so the beam direction has a visible reference frame.")
        self.chk_show_geom.stateChanged.connect(self._update_plot)
        ctl.addWidget(self.chk_show_geom)
        ctl.addStretch(1)
        v.addLayout(ctl)

        # GL widget
        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor((24, 24, 28))
        self.view.setCameraPosition(distance=3.0, elevation=22, azimuth=50)
        v.addWidget(self.view, 1)

        # Axes
        self._grid_items = []
        self._make_grids()
        self._make_axes()
        self._mesh = None
        self._board_items = []   # GL items representing the antenna outline

    def _make_grids(self):
        for it in self._grid_items:
            self.view.removeItem(it)
        self._grid_items = []
        g_xy = gl.GLGridItem(); g_xy.setSize(2, 2); g_xy.setSpacing(0.2, 0.2)
        g_xy.setColor((90, 90, 110, 120))
        self.view.addItem(g_xy)
        self._grid_items.append(g_xy)

    def _make_axes(self):
        # X = red, Y = green, Z = blue
        for ax, color, label in [((1,0,0), (255, 80, 80, 255), "+X"),
                                  ((0,1,0), (80, 220, 100, 255), "+Y"),
                                  ((0,0,1), (100, 140, 255, 255), "+Z")]:
            L = 1.1
            pts = np.array([[0, 0, 0], [ax[0]*L, ax[1]*L, ax[2]*L]])
            line = gl.GLLinePlotItem(pos=pts, color=np.array([color])/255,
                                     width=2, antialias=True)
            self.view.addItem(line)
            # Axis-tip label so the user can read the orientation directly
            # in the 3D viewport — pyqtgraph supports GLTextItem in newer
            # versions; fall back gracefully if not available.
            try:
                txt = gl.GLTextItem(
                    pos=(ax[0]*L*1.06, ax[1]*L*1.06, ax[2]*L*1.06),
                    text=label, color=color)
                self.view.addItem(txt)
            except AttributeError:
                pass

    def _toggle_grid(self, *_):
        vis = self.chk_grid.isChecked()
        for it in self._grid_items:
            it.setVisible(vis)

    def set_pattern(self, ctx, results, pattern_fn):
        """Set a pattern function U(θ, φ) — will rebuild the surface."""
        self._ctx = ctx
        self._results = results
        self._pattern_fn = pattern_fn
        self._update_plot()

    def _update_plot(self):
        if self._pattern_fn is None:
            return
        n = self.sl_res.value()
        theta = np.linspace(0, np.pi, n)
        phi = np.linspace(0, 2*np.pi, n)
        TH, PH = np.meshgrid(theta, phi, indexing="ij")
        U = np.abs(self._pattern_fn(TH, PH, self._ctx, self._results))
        Umax = np.max(U)
        if Umax == 0:
            U = np.ones_like(U) * 1e-3
            Umax = 1e-3
        Un = U / Umax

        log_mode = self.cb_log.currentIndex()
        if log_mode == 0:
            R = Un
            color_scalar = Un
        else:
            floor = -30.0 if log_mode == 1 else -40.0
            with np.errstate(divide="ignore"):
                Udb = 20 * np.log10(np.maximum(Un, 1e-10))
            Udb = np.clip(Udb, floor, 0)
            R = (Udb - floor) / (-floor)   # 0..1
            color_scalar = R

        X = R * np.sin(TH) * np.cos(PH)
        Y = R * np.sin(TH) * np.sin(PH)
        Z = R * np.cos(TH)

        # Build mesh triangles
        verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
        n_th, n_ph = TH.shape
        faces = []
        face_colors = []
        cmap = mpl.colormaps.get_cmap("turbo")
        for i in range(n_th - 1):
            for j in range(n_ph - 1):
                a = i * n_ph + j
                b = i * n_ph + (j + 1)
                c = (i + 1) * n_ph + j
                d = (i + 1) * n_ph + (j + 1)
                faces.append([a, b, d])
                faces.append([a, d, c])
                m1 = 0.25 * (color_scalar[i, j] + color_scalar[i, j+1]
                             + color_scalar[i+1, j] + color_scalar[i+1, j+1])
                face_colors.append(cmap(m1))
                face_colors.append(cmap(m1))
        faces = np.array(faces)
        face_colors = np.array(face_colors)

        md = gl.MeshData(vertexes=verts, faces=faces, faceColors=face_colors)
        if self._mesh is not None:
            self.view.removeItem(self._mesh)
        draw_edges = self.chk_wire.isChecked()
        self._mesh = gl.GLMeshItem(
            meshdata=md, smooth=False, shader="shaded",
            drawEdges=draw_edges, edgeColor=(1, 1, 1, 0.35),
            glOptions="translucent"
        )
        self.view.addItem(self._mesh)

        # Antenna outline overlay
        self._update_board_overlay()

    def _update_board_overlay(self):
        # Remove any previous board outline
        for it in self._board_items:
            self.view.removeItem(it)
        self._board_items = []
        if not self.chk_show_geom.isChecked():
            return
        if not self._results or "board_size" not in self._results:
            return
        # board_size is in METERS; we draw it normalized to ±0.5 of the
        # larger dimension scaled to the unit-radius pattern. Pick a scale
        # so the outline straddles the origin and stays visible under the
        # pattern lobes.
        bx_m, by_m = self._results["board_size"]
        ref = max(bx_m, by_m)
        if ref <= 0:
            return
        # Map the antenna's longest side to 1.4× pattern radius so the
        # outline pokes slightly past the typical main lobe.
        scale = 1.4 / ref
        bx = bx_m * scale
        by = by_m * scale
        # Build a filled translucent quad + an edge line loop, both at z=0.
        # Quad as two triangles
        v = np.array([
            [-bx/2, -by/2, 0.0],
            [ bx/2, -by/2, 0.0],
            [ bx/2,  by/2, 0.0],
            [-bx/2,  by/2, 0.0],
        ])
        faces = np.array([[0, 1, 2], [0, 2, 3]])
        colors = np.array([[1.0, 0.85, 0.30, 0.18]] * 2)
        quad = gl.GLMeshItem(
            vertexes=v, faces=faces, faceColors=colors,
            smooth=False, drawEdges=False,
            glOptions="translucent",
        )
        self.view.addItem(quad); self._board_items.append(quad)
        loop = np.array([v[0], v[1], v[2], v[3], v[0]])
        edge = gl.GLLinePlotItem(pos=loop,
                                 color=(1.0, 0.85, 0.30, 0.9),
                                 width=2, antialias=True)
        self.view.addItem(edge); self._board_items.append(edge)
