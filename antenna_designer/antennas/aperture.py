"""
Aperture antennas — rectangular slot, bowtie, Vivaldi, pyramidal horn.
"""
from __future__ import annotations
from pathlib import Path as FsPath
import numpy as np
from matplotlib import patches as mpatches
from matplotlib.path import Path as MPath

from .base import AntennaBase, Context, Input, Curve, register_antenna, C_LIGHT, ETA0
from calculators import microstrip
from plotting.cad import (
    LAYER_COLORS, style_ax, dim_horizontal, dim_vertical, dim_linear,
    angle_dim, leader, add_layer_legend, dim_board,
)


def _cst_ports_macro_dir() -> FsPath | None:
    """Return CST's Solver/Ports macro folder when installed locally."""
    candidates = [
        FsPath(r"C:\Program Files (x86)\CST Studio Suite 2025\Library\Macros\Solver\Ports"),
        FsPath(r"C:\Program Files\CST Studio Suite 2025\Library\Macros\Solver\Ports"),
        FsPath(r"C:\Program Files (x86)\CST Studio Suite 2024\Library\Macros\Solver\Ports"),
        FsPath(r"C:\Program Files\CST Studio Suite 2024\Library\Macros\Solver\Ports"),
    ]
    for path in candidates:
        if (path / "Calculate port extension coefficient_MS_5GHz.txt").exists():
            return path
    return None


def _load_cst_ms_port_table(path: FsPath) -> list[tuple[float, float, float]]:
    """Load CST's microstrip port-extension table, using the 1% error column."""
    rows: list[tuple[float, float, float]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return rows
    for line in lines[2:]:
        parts = line.split()
        if len(parts) >= 3:
            try:
                rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError:
                pass
    return rows


def _cst_table_value(rows: list[tuple[float, float, float]],
                     er: float, wh: float) -> float | None:
    for er_i, wh_i, k_i in rows:
        if abs(er_i - er) < 1e-12 and abs(wh_i - wh) < 1e-12:
            return k_i
    return None


def _tri_area(xa: float, ya: float, xb: float, yb: float,
              xc: float, yc: float) -> float:
    return abs((xb * ya - xa * yb) + (xc * yb - xb * yc) +
               (xa * yc - xc * ya)) / 2


def _cst_k_estimate(xp: float, yp: float,
                    xa: float, ya: float, za: float,
                    xb: float, yb: float, zb: float,
                    xc: float, yc: float, zc: float) -> float | None:
    pab = _tri_area(xp, yp, xa, ya, xb, yb)
    pcb = _tri_area(xp, yp, xc, yc, xb, yb)
    pac = _tri_area(xp, yp, xa, ya, xc, yc)
    cab = _tri_area(xc, yc, xa, ya, xb, yb)
    if cab <= 0 or (pab + pcb + pac) - cab >= cab / 1e6:
        return None
    a = ya * (zb - zc) + yb * (zc - za) + yc * (za - zb)
    b = za * (xb - xc) + zb * (xc - xa) + zc * (xa - xb)
    c = xa * (yb - yc) + xb * (yc - ya) + xc * (ya - yb)
    d = xa * (yb * zc - yc * zb) + xb * (yc * za - ya * zc) + xc * (ya * zb - yb * za)
    if abs(c) < 1e-12:
        return None
    return (-a * xp - b * yp + d) / c


def _cst_interpolate_port_k(rows: list[tuple[float, float, float]],
                            er: float, wh: float) -> float | None:
    ers = sorted({r[0] for r in rows})
    whs = sorted({r[1] for r in rows})
    er_low = max((v for v in ers if v <= er), default=None)
    er_high = min((v for v in ers if v >= er), default=None)
    wh_low = max((v for v in whs if v <= wh), default=None)
    wh_high = min((v for v in whs if v >= wh), default=None)
    if er_low is None or er_high is None or wh_low is None or wh_high is None:
        return None

    if er_low == er_high and wh_low == wh_high:
        return _cst_table_value(rows, er_low, wh_low)
    if er_low == er_high:
        k1 = _cst_table_value(rows, er_low, wh_low)
        k2 = _cst_table_value(rows, er_low, wh_high)
        if k1 is None or k2 is None or wh_high == wh_low:
            return None
        a = (k2 - k1) / (wh_high - wh_low)
        return a * wh + (k1 - a * wh_low)
    if wh_low == wh_high:
        k1 = _cst_table_value(rows, er_low, wh_low)
        k2 = _cst_table_value(rows, er_high, wh_low)
        if k1 is None or k2 is None or er_high == er_low:
            return None
        a = (k2 - k1) / (er_high - er_low)
        return a * er + (k1 - a * er_low)

    k_ll = _cst_table_value(rows, er_low, wh_low)
    k_hl = _cst_table_value(rows, er_high, wh_low)
    k_lh = _cst_table_value(rows, er_low, wh_high)
    k_hh = _cst_table_value(rows, er_high, wh_high)
    if None in (k_ll, k_hl, k_lh, k_hh):
        return None

    k_c = (k_hh + k_ll) / 2 if (k_hh + k_ll) / 2 > (k_hl + k_lh) / 2 else (k_hl + k_lh) / 2
    er_c = (er_low + er_high) / 2
    wh_c = (wh_low + wh_high) / 2
    triangles = (
        (er_low, wh_low, k_ll, er_high, wh_low, k_hl),
        (er_high, wh_low, k_hl, er_high, wh_high, k_hh),
        (er_high, wh_high, k_hh, er_low, wh_high, k_lh),
        (er_low, wh_high, k_lh, er_low, wh_low, k_ll),
    )
    for xa, ya, za, xb, yb, zb in triangles:
        k = _cst_k_estimate(er, wh, er_c, wh_c, k_c, xa, ya, za, xb, yb, zb)
        if k is not None:
            return k
    return None


def _cst_microstrip_port_k(er: float, wh: float,
                           fmin_ghz: float, fmax_ghz: float) -> float | None:
    """Match CST's bundled microstrip port-extension k lookup."""
    ports_dir = _cst_ports_macro_dir()
    if ports_dir is None or wh <= 0:
        return None
    freq_names = {
        0.1: "0.1GHz",
        1.0: "1GHz",
        2.0: "2GHz",
        5.0: "5GHz",
        10.0: "10GHz",
        15.0: "15GHz",
        20.0: "20GHz",
    }
    freqs = sorted(freq_names)
    f_low = max((f for f in freqs if f <= fmin_ghz), default=0.0)
    f_high = min((f for f in freqs if f >= fmax_ghz), default=1e6)
    k_values = []
    for freq in freqs:
        if f_low <= freq <= f_high:
            table = _load_cst_ms_port_table(
                ports_dir / f"Calculate port extension coefficient_MS_{freq_names[freq]}.txt")
            k = _cst_interpolate_port_k(table, er, wh)
            if k is not None:
                k_values.append(k)
    if not k_values:
        return None
    return np.floor(max(k_values) * 100) / 100


# ============================================================================
# Rectangular Slot
# ============================================================================

@register_antenna("Rectangular Slot", category="Aperture")
class RectangularSlot(AntennaBase):
    notes = "Booker's complementary relation: Z_slot · Z_dipole = η₀²/4."
    polarization = "linear  (E perpendicular to slot long axis)"
    beam_axis = "bidirectional, broadside (±Z to the ground plane)"
    bandwidth_note = "narrowband (~5 %), set by slot length"

    def inputs(self):
        return [
            Input("slot_W", "Slot width (units)", "2.0"),
        ]

    def compute(self, ctx, params):
        W = ctx.m(params.get("slot_W", "2.0"))
        # Slot resonance ≈ λ/2 in effective medium (air + substrate)
        ereff = (ctx.er + 1) / 2
        L = 0.5 * C_LIGHT / (ctx.fr * np.sqrt(ereff))
        # Complementary dipole impedance ≈ 73 Ω → slot ≈ η²/(4·73) ≈ 486 Ω
        Z_slot = ETA0 ** 2 / (4 * 73.1)
        # Feed offset to match ctx.z0 (microstrip crossing the slot, Balanis Ch. 12):
        # offset from slot center using cos² law:
        offset = (L / np.pi) * np.arccos(np.sqrt(ctx.z0 / Z_slot)) \
                 if ctx.z0 < Z_slot else 0.0
        feed = microstrip.synthesize(ctx.z0, ctx.er, ctx.h)
        return {"L": L, "W": W, "Z_slot": Z_slot, "offset": offset,
                "W_feed": feed["W"], "Ereff": ereff,
                "board_size": (L + 2 * ctx.Ls, W + 2 * ctx.Ws)}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Slot L         = {r['L']*m:.3f} {u}",
            f"  Slot W         = {r['W']*m:.3f} {u}",
            f"  Z_slot (edge)  = {r['Z_slot']:.0f} Ω",
            f"  Feed offset    = {r['offset']*m:.3f} {u}  (match to {ctx.z0:.1f} Ω)",
            f"  Feed line W    = {r['W_feed']*m:.3f} {u}",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, W = r["L"] * m, r["W"] * m
        Ls, Ws = ctx.Ls * m, ctx.Ws * m
        wf = r["W_feed"] * m
        off = r["offset"] * m
        style_ax(ax.figure, ax, "Rectangular Slot (in ground plane)", equal=True)
        # Ground plane
        ax.add_patch(mpatches.Rectangle(
            (-L/2 - Ls, -W/2 - Ws), L + 2*Ls, W + 2*Ws,
            facecolor=LAYER_COLORS["copper"], zorder=1))
        # Slot = hole
        ax.add_patch(mpatches.Rectangle(
            (-L/2, -W/2), L, W, facecolor=LAYER_COLORS["substrate"], zorder=2))
        # Feed line crossing slot (dashed — on opposite layer)
        ax.add_patch(mpatches.Rectangle(
            (off - wf/2, -W/2 - Ws), wf, W + 2*Ws,
            linestyle="--", edgecolor="cyan", fill=False, lw=1.2, zorder=3))
        dim_horizontal(ax, -L/2, L/2, W/2 + Ws*0.3, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -W/2, W/2, -L/2 - Ls*0.3, f"W = {W:.2f}", offset=0)
        # offset dim parked below the slot in the open ground area so it
        # isn't drawn on top of the dashed feed trace.
        dim_horizontal(ax, 0, off, -W/2 - Ws*0.45, f"offset = {off:.2f}",
                       offset=0, color=LAYER_COLORS["dim_alt"])

        dim_board(ax, -L/2 - Ls, L/2 + Ls, -W/2 - Ws, W/2 + Ws,
                  pad_frac=0.10)

        add_layer_legend(ax, [
            (LAYER_COLORS["copper"], "Ground plane"),
            (LAYER_COLORS["substrate"], "Slot aperture"),
            ("cyan", "Feed (opposite side)"),
        ], loc="upper right")
        ax.margins(0.18)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "Slot — Magnetic Current |M|", equal=True, grid=False)
        L, W = r["L"] * ctx.out_mult, r["W"] * ctx.out_mult
        X, Y = np.meshgrid(np.linspace(-L/2, L/2, 200),
                           np.linspace(-W/2, W/2, 80))
        M = np.abs(np.cos(np.pi * X / L))
        im = ax.contourf(X, Y, M, 60, cmap="magma")
        ax.plot([-L/2, L/2, L/2, -L/2, -L/2],
                [-W/2, -W/2, W/2, W/2, -W/2], "w-", lw=1.0)
        cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=LAYER_COLORS["text"])

    def pattern(self, theta, phi, ctx, r):
        # Slot in ground → complementary to dipole → pattern like dipole (bidirectional)
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        kL = k0 * r["L"]
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        with np.errstate(divide="ignore", invalid="ignore"):
            num = np.cos(kL/2 * np.cos(theta_b)) - np.cos(kL/2)
            den = np.sin(theta_b)
            F = np.where(np.abs(den) < 1e-9, 0.0, np.abs(num) / np.abs(den))
        return F


# ============================================================================
# Bowtie (planar)
# ============================================================================

@register_antenna("Bowtie (Planar)", category="Aperture")
class Bowtie(AntennaBase):
    notes = "Flare angle trades bandwidth ↔ gain. 60° is a balanced starting point."
    polarization = "linear  (E along the flare tip-to-tip axis)"
    beam_axis = "broadside ±Z (bidirectional)"
    bandwidth_note = "wideband (~50 % or more depending on flare)"

    def inputs(self):
        return [Input("flare_deg", "Flare angle (°)", "60")]

    def compute(self, ctx, params):
        flare = float(params.get("flare_deg", "60"))
        L = 0.5 * ctx.lambda0
        W = 2 * (L / 2 * np.tan(np.radians(flare) / 2))
        # Input impedance (approx, Brown-Woodward):
        # For α = flare half-angle, Z ≈ 120 · ln(cot(α/2))  ohms (infinite bowtie)
        alpha = np.radians(flare) / 2
        Z_in = 120 * np.log(1 / np.tan(alpha / 2)) if alpha > 0 else np.nan
        # Triangles as parametric curves for export
        tri_left  = [(-L/2,  W/2), (0.0, 0.0), (-L/2, -W/2), (-L/2,  W/2)]
        tri_right = [( L/2,  W/2), (0.0, 0.0), ( L/2, -W/2), ( L/2,  W/2)]
        curves = [
            Curve(name="Left triangle (apex at origin)",
                  equation="vertices: (−L/2, ±W/2) and (0, 0)",
                  parameters={"L": (L, "m"), "W": (W, "m")},
                  points_m=tri_left, closed=True),
            Curve(name="Right triangle (apex at origin)",
                  equation="vertices: (+L/2, ±W/2) and (0, 0)",
                  parameters={"L": (L, "m"), "W": (W, "m")},
                  points_m=tri_right, closed=True),
        ]
        bw = {
            "f_low_hz": ctx.fr * 0.7,
            "f_high_hz": ctx.fr * 1.5,
            "fractional": 0.8 / 1.1,
            "note": f"Wideband — wider flare gives more BW (flare={flare:.0f}°).",
        }
        return {"L": L, "W": W, "flare": flare, "Z_in": Z_in,
                "board_size": (L + 2 * ctx.Ls, W + 2 * ctx.Ws),
                "curves": curves, "bandwidth": bw}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Tip-to-tip L   = {r['L']*m:.3f} {u}",
            f"  Base width W   = {r['W']*m:.3f} {u}",
            f"  Flare          = {r['flare']:.1f}°",
            f"  Z_in (infinite bowtie est.) = {r['Z_in']:.0f} Ω",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, W = r["L"] * m, r["W"] * m
        Ls, Ws = ctx.Ls * m, ctx.Ws * m
        style_ax(ax.figure, ax, "Bowtie — Planar", equal=True)
        ax.add_patch(mpatches.Rectangle(
            (-L/2 - Ls, -W/2 - Ws), L + 2*Ls, W + 2*Ws,
            facecolor=LAYER_COLORS["substrate"], zorder=1))
        # Two triangles
        ax.add_patch(mpatches.Polygon([[0, 0], [L/2, W/2], [L/2, -W/2]],
                                       facecolor=LAYER_COLORS["copper"],
                                       edgecolor=LAYER_COLORS["copper_edge"], zorder=2))
        ax.add_patch(mpatches.Polygon([[0, 0], [-L/2, W/2], [-L/2, -W/2]],
                                       facecolor=LAYER_COLORS["copper"],
                                       edgecolor=LAYER_COLORS["copper_edge"], zorder=2))
        ax.plot([0], [0], "o", color="red", markersize=5, zorder=5)
        dim_horizontal(ax, -L/2, L/2, -W/2 - Ws*0.3, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -W/2, W/2, L/2 + Ls*0.25, f"W = {W:.2f}", offset=0)
        angle_dim(ax, (0, 0), (L/2, W/2), (L/2, -W/2),
                  f"{r['flare']:.0f}°",
                  radius=L * 0.18, color=LAYER_COLORS["dim_special"])

        dim_board(ax, -L/2 - Ls, L/2 + Ls, -W/2 - Ws, W/2 + Ws,
                  pad_frac=0.10)

        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"], "Substrate"),
            (LAYER_COLORS["copper"], "Copper"),
        ], loc="lower left")
        ax.margins(0.16)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "Bowtie Surface Current", equal=True, grid=False)
        L, W = r["L"] * ctx.out_mult, r["W"] * ctx.out_mult
        X, Y = np.meshgrid(np.linspace(-L/2, L/2, 260),
                           np.linspace(-W/2, W/2, 200))
        # Mask to bowtie shape
        slope = (W / 2) / (L / 2)
        bowtie_mask = ((X >= 0) & (np.abs(Y) <= slope * X)) | \
                      ((X <= 0) & (np.abs(Y) <= -slope * X))
        # Approximate current magnitude: larger near feed, tapers to tip
        current = np.abs(np.cos(np.pi * X / L)) / (1 + np.abs(Y) / max(W, 1e-9))
        current[~bowtie_mask] = np.nan
        im = ax.contourf(X, Y, current, 60, cmap="inferno")
        cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=LAYER_COLORS["text"])

    def pattern(self, theta, phi, ctx, r):
        # Bowtie broad pattern — approximate as shortened dipole along x
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        kL = k0 * r["L"]
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        phi_b = np.broadcast_to(phi, np.broadcast_shapes(theta.shape, phi.shape))
        # Angle from x axis
        cos_from_x = np.sin(theta_b) * np.cos(phi_b)
        theta_x = np.arccos(np.clip(cos_from_x, -1, 1))
        with np.errstate(divide="ignore", invalid="ignore"):
            num = np.cos(kL/2 * np.cos(theta_x)) - np.cos(kL/2)
            den = np.sin(theta_x)
            F = np.where(np.abs(den) < 1e-9, 0.0, np.abs(num) / np.abs(den))
        # broaden a bit with flare
        return F ** 0.9


# ============================================================================
# Vivaldi (Tapered Slot / TSA)
# ============================================================================

@register_antenna("Vivaldi (Exponential TSA)", category="Aperture")
class Vivaldi(AntennaBase):
    notes = (
        "Exponentially tapered slot (Gibson 1979). Wideband end-fire radiator fed "
        "by a microstrip-to-slotline balun. The base-panel 'Resonant freq' is used "
        "only to size the microstrip/balun; the radiator's bandwidth is set by "
        "f_low / f_high and the physical taper length."
    )
    polarization = "linear  (E across the slot, vertical when board is horizontal)"
    beam_axis = "end-fire along +X (taper opens toward +X)"
    bandwidth_note = "wideband (multi-octave)"

    def inputs(self):
        return [
            Input("f_low_GHz",  "Low edge freq f_low (GHz)", "2.0",
                  tooltip="Sets aperture mouth: W_ap ≈ λ₀/2 at f_low."),
            Input("f_high_GHz", "High edge freq f_high (GHz)", "10.0",
                  tooltip="Sets throat (start) width: w₀ ≈ λ₀/30 at f_high."),
            Input("length",     "Taper length L", "80.0", unit="units",
                  tooltip="Physical length of the exponential flare (mm/mils)."),
            Input("w0",         "Throat width w₀ (0 = auto)", "0.0", unit="units",
                  tooltip="Narrow end of the slot; blank/0 → auto from f_high."),
            Input("W_ap",       "Mouth / aperture W_ap (0 = auto)", "0.0", unit="units",
                  tooltip="Mouth of the taper; blank/0 → auto from f_low."),
            Input("cavity_dia", "Back-cavity Ø (0 = auto)", "0.0", unit="units",
                  tooltip="Circular slotline termination; auto uses λ_slot/3 at f_low."),
            Input("stub_ratio", "Radial-stub length (λ_g fraction)", "0.25",
                  tooltip="¼ λ_g microstrip stub — classic virtual short."),
            Input("stub_angle", "Radial-stub sector half-angle (deg)", "45"),
            Input("feed_Z",     "Feed microstrip Z₀ (Ω)", "50"),
            Input("feed_w_slot","Microstrip width at slot crossing (0 = no taper)",
                  "0.0", unit="units",
                  tooltip="Width of the vertical microstrip where it crosses "
                          "the slot. Set narrower than W_feed for a linear "
                          "impedance taper into the high-Z slotline (improves "
                          "balun bandwidth). 0 → constant width."),
            Input("miter_frac","Corner miter (fraction of W_feed, 0 = no miter)",
                  "0.6",
                  tooltip="Chamfer at the 90° L-bend, sized as a fraction of "
                          "W_feed (Douville-James ≈ 0.5–0.6). Cuts excess "
                          "corner capacitance so the bend stays at Z₀."),
            Input("feed_side",  "SMA connector side", "left",
                  choices=["left", "bottom"],
                  tooltip="Board edge the SMA sits on. 'left' = same side as the "
                          "cavity; microstrip L-turns on the bottom layer to "
                          "cross the slot perpendicular."),
            Input("margin_back","Board margin behind cavity", "4.0", unit="units"),
            Input("margin_side","Board margin beside taper", "4.0", unit="units"),
        ]

    def compute(self, ctx, params):
        fL = float(params.get("f_low_GHz",  "2.0")) * 1e9
        fH = float(params.get("f_high_GHz", "10.0")) * 1e9
        if fH <= fL:
            fH = fL * 2

        L = ctx.m(params.get("length", "80.0"))                 # taper length
        # Auto defaults: W_ap = λ_low/2, w0 = λ_high/30
        W_ap_default = 0.5 * C_LIGHT / fL
        w0_default   = (C_LIGHT / fH) / 30.0
        W_ap = ctx.m_or(params.get("W_ap"), W_ap_default)
        w0   = ctx.m_or(params.get("w0"),   w0_default)
        if w0 >= W_ap:
            w0 = W_ap * 0.05

        # Exponential taper rate so y(L) = W_ap/2 starting from y(0) = w0/2
        R = np.log(W_ap / w0) / L

        feed_Z     = float(params.get("feed_Z", "50"))
        # Microstrip feed (balun) — uses ctx.fr as the design/center freq.
        # This is intentionally Vivaldi-specific: the GUI exposes feed_Z as
        # an antenna parameter, so use it here instead of the global ctx.z0.
        feed = microstrip.synthesize(feed_Z, ctx.er, ctx.h)
        # Slotline guide wavelength (rough): εr_slot ≈ (εr + 1)/2
        er_slot = (ctx.er + 1) / 2
        lam_g_slot_at_fr   = C_LIGHT / (ctx.fr * np.sqrt(er_slot))
        lam_g_slot_at_fL   = C_LIGHT / (fL   * np.sqrt(er_slot))
        lam_g_strip        = C_LIGHT / (ctx.fr * np.sqrt(feed["Ereff"]))

        # Feed crosses the slotline at λ_g_slot/4 from the throat / cavity
        # junction. The board-centered CST export later subtracts center_x.
        feed_cross_x = lam_g_slot_at_fr / 4

        cavity_dia = ctx.m_or(params.get("cavity_dia"),
                              lam_g_slot_at_fL / 3)
        stub_ratio = float(params.get("stub_ratio", "0.25"))
        stub_angle = float(params.get("stub_angle", "45"))
        stub_len   = stub_ratio * lam_g_strip
        # Vertical microstrip width at the slot crossing. 0 → same as W_feed
        # (no taper). Used to improve match to the high-impedance slotline.
        feed_w_slot = ctx.m(params.get("feed_w_slot", "0.0"))
        if feed_w_slot <= 0 or feed_w_slot > feed["W"]:
            feed_w_slot = feed["W"]
        try:
            miter_frac = float(params.get("miter_frac", "0.6"))
        except (TypeError, ValueError):
            miter_frac = 0.6
        miter_frac = max(0.0, min(0.9, miter_frac))
        feed_side  = str(params.get("feed_side", "left")).strip().lower()
        if feed_side not in ("left", "bottom"):
            feed_side = "left"
        m_back     = ctx.m(params.get("margin_back", "4.0"))
        m_side     = ctx.m(params.get("margin_side", "4.0"))

        # Cavity centre. Original code placed the cavity tangent to x=0 at
        # the origin, which leaves a small disconnect between the cavity
        # circle and the throat (the slot opens to (0, ±w0/2) but the
        # cavity only touches (0, 0)). Shifting cav_cx so the cavity passes
        # EXACTLY through (0, ±w0/2) makes the etched slot+cavity a single
        # continuous opening — no gap, no overlap.
        cav_r = 0.5 * cavity_dia
        if cav_r > w0 / 2:
            cav_cx_offset = float(np.sqrt(cav_r ** 2 - (w0 / 2) ** 2))
        else:
            cav_cx_offset = cav_r
        cav_cx = -cav_cx_offset                        # cavity centre x (m)
        # Board footprint (cavity leftmost point sits at cav_cx − cav_r)
        cav_left = cav_cx - cav_r
        board_len = L - cav_left + m_back              # x extent
        board_wid = W_ap + 2 * m_side                  # y extent

        # Slotline width where the microstrip crosses it — needed (together
        # with the microstrip width) to design the microstrip-to-slotline
        # balun. The slot follows the exponential taper, capped at the mouth.
        slot_w_feed = min(w0 * np.exp(R * feed_cross_x), W_ap)

        # Microstrip feed-trace run length on the bottom layer.
        # y_run is the y-coordinate of the horizontal microstrip run. It
        # sits below the slot at ~55 % of the board half-height so the
        # SMA pad clears the slot's lower edge.
        W_h = feed["W"]                                # horizontal width
        W_v = feed_w_slot                              # width at slot crossing
        if feed_side == "left":
            y_run_pos = 0.55 * (board_wid / 2)
            y_run     = -y_run_pos                     # actual y, below origin
            feed_len  = (feed_cross_x - cav_left + m_back) + y_run_pos
        else:
            y_run     = -board_wid / 2                 # bottom edge
            feed_len  = board_wid / 2

        miter_d = miter_frac * W_h
        # Build the L-shaped feed polygon (CCW) in NATIVE plot coords.
        # Outer corner is bottom-right; miter chamfers it. Vertical tapers
        # linearly from W_h at the corner-top to W_v at the slot.
        feed_poly = []
        if feed_side == "left":
            feed_poly.append((cav_left - m_back, y_run + W_h/2))             # 1: top-left at SMA
            feed_poly.append((feed_cross_x - W_h/2, y_run + W_h/2))           # 2: inner-corner top
            feed_poly.append((feed_cross_x - W_v/2, 0.0))                     # 3: tapered to slot (left)
            feed_poly.append((feed_cross_x + W_v/2, 0.0))                     # 4: tapered to slot (right)
            feed_poly.append((feed_cross_x + W_h/2, y_run + W_h/2))           # 5: back down to corner top (outer)
            if miter_d > 0:
                feed_poly.append((feed_cross_x + W_h/2, y_run - W_h/2 + miter_d))
                feed_poly.append((feed_cross_x + W_h/2 - miter_d, y_run - W_h/2))
            else:
                feed_poly.append((feed_cross_x + W_h/2, y_run - W_h/2))      # outer corner (no miter)
            feed_poly.append((cav_left - m_back, y_run - W_h/2))             # bottom-left at SMA
        else:
            # Bottom-feed: straight vertical microstrip from board bottom up
            # to the slot. Tapered if W_v != W_h, no corner so no miter.
            feed_poly = [
                (feed_cross_x - W_h/2, y_run),
                (feed_cross_x - W_v/2, 0.0),
                (feed_cross_x + W_v/2, 0.0),
                (feed_cross_x + W_h/2, y_run),
            ]

        # Quick sanity checks
        warn = []
        if L < 0.8 * (C_LIGHT / fL):
            warn.append(f"L < 0.8·λ_low ({(C_LIGHT/fL)*1e3:.1f} mm); gain will be low.")
        if W_ap < 0.45 * (C_LIGHT / fL):
            warn.append(f"W_ap < λ_low/2; poor low-freq response.")
        if w0 >= slot_w_feed * 0.999 and feed_cross_x > 0:
            pass  # throat already wide — informational only

        # --- Parametric curves for CAD import ------------------------------
        # 1) Exponential taper edges (slot half-width above and below y=0).
        #    Sample with 60 points so the polyline is smooth in CST.
        N_pts = 60
        xs = np.linspace(0.0, L, N_pts)
        y_upper = np.minimum((w0 / 2) * np.exp(R * xs), W_ap / 2)
        # 2) Back-cavity circle (drawn as a full circle for the geometry view
        #    AND a "back arc" portion that connects the throat ends as part
        #    of the etched slot+cavity opening).
        cav_t = np.linspace(0, 2 * np.pi, 73)
        cav_pts = [(cav_cx + cav_r * np.cos(t), cav_r * np.sin(t)) for t in cav_t]
        # Angle at which the cavity passes through the throat (0, ±w0/2).
        if cav_r > w0 / 2:
            a0 = float(np.arcsin((w0 / 2) / cav_r))
        else:
            a0 = 0.0
        # Back arc: from (0, −w0/2) going CW around the back to (0, +w0/2).
        cav_back_angles = np.linspace(-a0, a0 - 2 * np.pi, 80)
        cav_back_pts = [(cav_cx + cav_r * np.cos(a), cav_r * np.sin(a))
                        for a in cav_back_angles]

        # CST analytical expressions use the user's display unit (mm or mils).
        mu = ctx.out_mult
        w0_d   = w0   * mu
        R_d    = R    / mu          # 1/m → 1/display-unit
        L_d    = L    * mu
        W_ap_d = W_ap * mu
        cav_cx_d = cav_cx * mu
        cav_r_d  = cav_r  * mu

        curves = [
            Curve(
                name="Upper taper edge",
                equation="y_upper(x) = (w0/2) · exp(R · x),  clipped to W_ap/2",
                parameters={
                    "w0":   (w0,   "m"),
                    "R":    (R,    "1/m"),
                    "W_ap": (W_ap, "m"),
                    "x":    ((0.0, L), "m"),
                },
                points_m=[(float(x), float(y)) for x, y in zip(xs, y_upper)],
                note="The lower edge is the mirror y_lower(x) = −y_upper(x).",
                cst={
                    "x_t":  "t - center_x",
                    "y_t":  "(w0/2)*exp((ln(W_ap/w0)/L)*t)",
                    "z_t":  "0",
                    "t_min": "0",
                    "t_max": "L",
                    "t_unit": ctx.unit_str,
                },
                dxf_combined=False,
            ),
            Curve(
                name="Lower taper edge (mirror of upper)",
                equation="y_lower(x) = −(w0/2) · exp(R · x)",
                parameters={
                    "w0":   (w0,   "m"),
                    "R":    (R,    "1/m"),
                    "W_ap": (W_ap, "m"),
                    "x":    ((0.0, L), "m"),
                },
                points_m=[(float(x), float(-y)) for x, y in zip(xs, y_upper)],
                cst={
                    "x_t":  "t - center_x",
                    "y_t":  "-(w0/2)*exp((ln(W_ap/w0)/L)*t)",
                    "z_t":  "0",
                    "t_min": "0",
                    "t_max": "L",
                    "t_unit": ctx.unit_str,
                },
                dxf_combined=False,
            ),
            Curve(
                name="Aperture right edge",
                equation="x = L,  y ∈ [−W_ap/2, +W_ap/2]",
                parameters={"L": (L, "m"), "W_ap": (W_ap, "m")},
                points_m=[(float(L), float(-W_ap/2)),
                          (float(L), float( W_ap/2))],
                cst={
                    "x_t":  "L - center_x",
                    "y_t":  "t",
                    "z_t":  "0",
                    "t_min": "-W_ap/2",
                    "t_max": "W_ap/2",
                    "t_unit": ctx.unit_str,
                },
                note="Component of the closed slot+cavity boundary.",
                dxf_combined=False,
            ),
            Curve(
                name="Back-cavity arc (back side only)",
                equation=("(x − cav_cx)² + y² = cav_rad²,  arc from "
                          "(0,−w0/2) around the back to (0,+w0/2)"),
                parameters={
                    "cav_cx":  (cav_cx, "m"),
                    "cav_rad": (cav_r,  "m"),
                    "a0":      (a0,     "rad"),
                },
                points_m=cav_back_pts,
                cst={
                    "x_t":  "-sqrt(cav_rad^2 - (w0/2)^2) + cav_rad*cos(t) - center_x",
                    "y_t":  "cav_rad*sin(t)",
                    "z_t":  "0",
                    "t_min": "asin(w0/(2*cav_rad))",
                    "t_max": "2*pi - asin(w0/(2*cav_rad))",
                    "t_unit": "rad",
                },
                note=("Component of the closed slot+cavity boundary. "
                      "Goes CCW from a0 to 2π−a0 along the back of the "
                      "cavity (away from the slot)."),
                dxf_combined=False,
            ),
            Curve(
                name="Back-cavity circle (full, for reference)",
                equation="(x − cav_cx)² + y² = cav_rad²",
                parameters={
                    "cav_cx":  (cav_cx, "m"),
                    "cav_rad": (cav_r,  "m"),
                },
                points_m=cav_pts,
                closed=True,
                cst={
                    "x_t":  "-sqrt(cav_rad^2 - (w0/2)^2) + cav_rad*cos(t) - center_x",
                    "y_t":  "cav_rad*sin(t)",
                    "z_t":  "0",
                    "t_min": "0",
                    "t_max": "2*pi",
                    "t_unit": "rad",
                },
                note=("Reference only — its back-side arc is already "
                      "included in the closed boundary, so this full circle "
                      "is omitted from the combined DXF."),
                dxf_combined=False,
            ),
        ]

        # ---- Microstrip feed polygon (bottom-layer copper) ----------------
        curves.append(Curve(
            name="Microstrip feed (bottom layer)",
            equation=("L-shaped microstrip on the BOTTOM layer (z = −h). "
                      "Horizontal run width W_feed; vertical tapers from "
                      "W_feed at the corner to feed_w_slot at the slotline "
                      "crossing; 45° miter at the outer corner."),
            parameters={
                "W_feed":      (feed["W"],   "m"),
                "feed_w_slot": (W_v,         "m"),
                "miter_d":     (miter_d,     "m"),
                "feed_cross_x":(feed_cross_x,"m"),
                "y_run":       (y_run,       "m"),
            },
            points_m=feed_poly,
            closed=True,
            note=("Drop on the BOTTOM copper layer (z = −h). Pair with the "
                  "radial stub at the slot crossing (= virtual short → "
                  "broadband balun). Tapered vertical impedance-matches the "
                  "high-Z slotline; mitred corner compensates the L-bend "
                  "capacitance so the bend stays at Z₀."),
        ))

        # ---- Radial stub (bottom-layer copper, virtual short at slot) -----
        # Sector polygon with a FINITE apex of width W_v sharing the same
        # edge as the microstrip's top side at y=0. The apex would be a
        # single point (and create a zero-width connection to the
        # microstrip — bad for meshing AND physically unrealistic) if we
        # drew it from a true apex. Instead the base of the sector is the
        # microstrip-width segment, and the sector sides come in tangent
        # to the arc from the two corners of that segment.
        stub_half = np.radians(stub_angle)
        theta_c   = np.pi / 2.0                       # opens upward
        n_arc     = 60
        stub_arc_angles = np.linspace(theta_c - stub_half,
                                      theta_c + stub_half, n_arc)
        # Two apex corners (shared with microstrip top edge)
        apex_L = (float(feed_cross_x - W_v / 2), 0.0)
        apex_R = (float(feed_cross_x + W_v / 2), 0.0)
        # Arc points centred on the slot crossing
        arc_pts = [(float(feed_cross_x + stub_len * np.cos(a)),
                    float(stub_len * np.sin(a))) for a in stub_arc_angles]
        # CCW traversal: right apex corner → arc (CCW from -half to +half
        # at theta_c) → left apex corner → close to right
        stub_pts = [apex_R] + arc_pts + [apex_L]
        curves.append(Curve(
            name="Radial stub (bottom layer)",
            equation=("sector centred at the slot crossing, radius stub_r, "
                      "full sector angle = stub_ang°, opening towards +Y, "
                      "with apex of width W_v shared with microstrip top"),
            parameters={
                "stub_r":      (stub_len,      "m"),
                "stub_ang":    (2 * stub_angle, "deg"),
                "feed_cross_x":(feed_cross_x,  "m"),
                "feed_w_slot": (W_v,           "m"),
            },
            points_m=stub_pts,
            closed=True,
            note=("Bottom-layer copper, union it with the L-feed. Apex is a "
                  "W_v-wide line segment shared with the microstrip top edge "
                  "so the Boolean union creates a real-width connection (no "
                  "zero-width contact). Virtual short at the slot — ¼-λ "
                  "stub with wider bandwidth than a straight-line stub."),
        ))

        # ---- Recommended: full slot+cavity boundary as one closed loop -----
        # Upper taper forward → vertical right edge → lower taper reversed →
        # back-cavity arc closing from (0, −w0/2) around the back to
        # (0, +w0/2). This polyline traces the ACTUAL etched copper
        # opening — one face, one Boolean subtraction in CST.
        upper = [(float(x), float(y)) for x, y in zip(xs, y_upper)]
        lower_rev = [(float(x), float(-y))
                     for x, y in zip(xs[::-1], y_upper[::-1])]
        slot_boundary = upper + lower_rev + cav_back_pts  # ends at (0,+w0/2)
        curves.append(Curve(
            name="Slot + cavity — closed boundary (recommended)",
            equation=("upper taper → right edge → lower taper → "
                      "back-cavity arc"),
            parameters={
                "L":    (L,    "m"),
                "W_ap": (W_ap, "m"),
                "w0":   (w0,   "m"),
                "R":    (R,    "1/m"),
                "cav_rad":(cav_r,  "m"),
                "cav_cx": (cav_cx, "m"),
            },
            points_m=slot_boundary,
            closed=True,
            note=("Import via the combined DXF, 'Cover Curve' to make a "
                  "face, then ONE Boolean subtraction from the ground "
                  "copper. The cavity arc on the back side closes the "
                  "loop so the slot and cavity are a single opening — "
                  "no second subtraction needed."),
        ))

        full_model_defaults = {
            "_unit":        ctx.unit_str,
            "fr_GHz":       ctx.fr / 1e9,
            "f_low_GHz":    fL / 1e9,
            "f_high_GHz":   fH / 1e9,
            "er":           ctx.er,
            "tan_d":        ctx.loss_tangent,
            "L":            L * mu,
            "W_ap":         W_ap * mu,
            "w0":           w0 * mu,
            "cav_rad":      cav_r * mu,
            "h":            ctx.h * mu,
            "t_cu":         0.035e-3 * mu,
            "W_feed":       feed["W"] * mu,
            "feed_w_slot":  W_v * mu,
            "miter_d":      miter_d * mu,
            "stub_r":       stub_len * mu,
            "stub_ang":     stub_angle * 2,
            "m_back":       m_back * mu,
            "m_side":       m_side * mu,
            "board_L":      board_len * mu,
            "board_W":      board_wid * mu,
            "center_x":     ((L + cav_left - m_back) / 2) * mu,
            "x_cross":      (feed_cross_x -
                             ((L + cav_left - m_back) / 2)) * mu,
            "y_run":        (y_run if feed_side == "left"
                             else -board_wid / 2) * mu,
            "x_sma":        ((cav_left - m_back) -
                             ((L + cav_left - m_back) / 2)) * mu,
            "port_margin":  1.5 * feed["W"] * mu,
        }
        port_k = _cst_microstrip_port_k(
            ctx.er, feed["W"] / ctx.h, fL / 1e9, fH / 1e9)
        if port_k is not None:
            full_model_defaults["port_k"] = port_k

        bandwidth = {
            "f_low_hz":  fL,
            "f_high_hz": fH,
            "fractional": 2 * (fH - fL) / (fH + fL),
            "note": "Wideband end-fire — set by taper length and aperture mouth.",
        }
        return {
            "L": L, "W_ap": W_ap, "w0": w0, "R_rate": R,
            "cavity_dia": cavity_dia, "stub_len": stub_len,
            "stub_angle_deg": stub_angle,
            "feed_cross_x": feed_cross_x,
            "W_feed": feed["W"], "feed_Z": feed_Z,
            "feed_side": feed_side,
            "Ereff_feed": feed["Ereff"],
            "lam_g_slot_at_fr": lam_g_slot_at_fr,
            "lam_g_slot_at_fL": lam_g_slot_at_fL,
            "lam_g_strip": lam_g_strip,
            "f_low": fL, "f_high": fH,
            "m_back": m_back, "m_side": m_side,
            "slot_w_feed": slot_w_feed, "feed_len": feed_len,
            "feed_w_slot": W_v, "miter_d": miter_d,
            "feed_poly": feed_poly,
            # board_size = (X_extent, Y_extent) in metres, matching CAD axes.
            # For the Vivaldi the taper opens along +X, so the long side is X.
            "board_size": (board_len, board_wid),
            # Board centre in the NATIVE plot frame — base.py translates
            # curves so this becomes (0,0,0) in CST exports.
            "board_center_m": ((L + cav_left - m_back) / 2, 0.0),
            "curves": curves,
            "bandwidth": bandwidth,
            "warnings": warn,
            # ---- Math & CST parametric recipe -----------------------------
            "math_equations": [
                ("Exponential taper",
                 "y(x) = ±(w0/2) · exp(R · x)"),
                ("Taper rate (auto-derived from aperture spec)",
                 "R = ln(W_ap / w0) / L"),
                ("Back-cavity circle",
                 "(x − cav_cx)² + y² = cav_rad²"),
                ("Cavity centre (cavity passes through (0, ±w0/2))",
                 "cav_cx = −√(cav_rad² − (w0/2)²)"),
                ("Cavity-throat angle",
                 "a0 = arcsin(w0 / (2·cav_rad))"),
                ("Microstrip-to-slotline crossing (λ_g_slot/4 at fr)",
                 "x_cross = c / (4·fr·√((εr+1)/2))"),
                ("Overall board length",
                 "board_L = L − (cav_cx − cav_rad) + m_back"),
                ("Overall board width",
                 "board_W = W_ap + 2·m_side"),
            ],
            "cst_parameters": {
                # CST's parameter-list expressions don't accept function
                # calls like sqrt() / asin() / ln(), so we keep the list to
                # plain values plus simple-arithmetic derived entries. The
                # transcendental formulas (R, cav_cx, throat angle) are
                # INLINED into the analytical-curve expressions in Step 2 —
                # that way tuning L, W_ap, w0, or cav_rad still propagates
                # automatically because the analytical-curve parser DOES
                # support those functions.
                "L":       {"value": L * mu,          "unit": ctx.unit_str,
                            "comment": "Taper length"},
                "W_ap":    {"value": W_ap * mu,       "unit": ctx.unit_str,
                            "comment": "Aperture (mouth) width"},
                "w0":      {"value": w0 * mu,         "unit": ctx.unit_str,
                            "comment": "Throat (slotline) width"},
                "cav_rad": {"value": cav_r * mu,      "unit": ctx.unit_str,
                            "comment": "Back-cavity radius "
                                       "(named cav_rad, NOT cav_r — "
                                       "cav_r is reserved in CST/VBA)"},
                "h":       {"value": ctx.h * mu,      "unit": ctx.unit_str,
                            "comment": "Substrate thickness"},
                "er":      {"value": ctx.er,          "unit": "",
                            "comment": "Substrate relative permittivity"},
                "W_feed":  {"value": feed["W"] * mu,  "unit": ctx.unit_str,
                            "comment": "Microstrip feed width — horizontal "
                                       f"run (Z0 = {feed_Z:.0f} Ω)"},
                "feed_w_slot":
                           {"value": W_v * mu,        "unit": ctx.unit_str,
                            "comment": "Microstrip width at slot crossing "
                                       "(vertical tapers W_feed → "
                                       "feed_w_slot)"},
                "miter_d": {"value": miter_d * mu,    "unit": ctx.unit_str,
                            "comment": "45° chamfer at the outer L-bend "
                                       "(≈ 0.5–0.6·W_feed; cancels bend "
                                       "capacitance)"},
                "stub_r":  {"value": stub_len * mu,   "unit": ctx.unit_str,
                            "comment": "Radial stub radius (virtual short "
                                       "at the slot)"},
                "stub_ang":{"value": stub_angle * 2,  "unit": "deg",
                            "comment": "Radial stub full sector angle"},
                "m_back":  {"value": m_back * mu,     "unit": ctx.unit_str,
                            "comment": "Substrate margin behind cavity"},
                "m_side":  {"value": m_side * mu,     "unit": ctx.unit_str,
                            "comment": "Substrate margin beside taper"},
                # --- derived (simple arithmetic only — no functions) ------
                "board_W":  {"formula": "W_ap + 2*m_side",
                             "value":   board_wid * mu,
                             "unit":    ctx.unit_str,
                             "comment": "Total board width"},
                # board_L needs sqrt() to be truly parametric, so it stays
                # a value. Update it manually (or rebuild the recipe) if
                # you retune w0 / cav_rad / m_back.
                "board_L":  {"value":   board_len * mu,
                             "unit":    ctx.unit_str,
                             "comment": "Total board length  "
                                        "(= L + sqrt(cav_rad^2 - (w0/2)^2) "
                                        "+ cav_rad + m_back)"},
                # center_x shifts the analytical curves onto a board you
                # built centred on the origin. Simple arithmetic, so CST's
                # parameter list accepts the formula and it stays parametric
                # with L.
                "center_x": {"formula": "L - board_L/2",
                             "value":   ((L + cav_left - m_back) / 2) * mu,
                             "unit":    ctx.unit_str,
                             "comment": "X-offset that maps native-frame "
                                        "curves onto a board centred at "
                                        "the origin"},
                # ---- Feed/stub placement (board-centered frame) -----------
                # These are stored as plain values (not formulas) so they're
                # sweep-friendly — the user typically tunes x_cross / y_run
                # to optimise the balun match.
                "x_cross": {"value":   (feed_cross_x -
                                        ((L + cav_left - m_back) / 2)) * mu,
                            "unit":    ctx.unit_str,
                            "comment": "X of microstrip↔slot crossing "
                                       "(board-centered). ≈ λ_g_slot/4 from "
                                       "cavity. SWEEP THIS to tune the "
                                       "balun centre frequency."},
                "y_run":   {"value":   (y_run if feed_side == "left"
                                        else -board_wid / 2) * mu,
                            "unit":    ctx.unit_str,
                            "comment": "Y of horizontal microstrip run "
                                       "(board-centered). Negative = below "
                                       "the slot."},
                "x_sma":   {"value":   ((cav_left - m_back) -
                                        ((L + cav_left - m_back) / 2)) * mu,
                            "unit":    ctx.unit_str,
                            "comment": "Left edge of microstrip "
                                       "(board-centered) — SMA pad sits here "
                                       "for the 'left' feed layout."},
                "port_margin":
                           {"value":   1.5 * feed["W"] * mu,
                            "unit":    ctx.unit_str,
                            "comment": "Waveguide-port margin around the "
                                       "microstrip launch. Increase if CST "
                                       "warns the port is too tightly clipped."},
                "t_cu":    {"value":   0.035e-3 * mu,
                            "unit":    ctx.unit_str,
                            "comment": "Copper thickness (default 1 oz ≈ "
                                       "0.035 mm). Used by the VBA macro "
                                       "for extruding the bottom layer."},
            },
            "cst_vba_macro": self._build_cst_vba_macro(feed_side, {
                # Values used as defaults inside the macro's EnsureParam
                # calls — must be expressed in the user's display units
                # because CST's parameter list is unitless and the project
                # uses ctx.unit_str globally.
                "h":            ctx.h * mu,
                "t_cu":         0.035e-3 * mu,
                "W_feed":       feed["W"] * mu,
                "feed_w_slot":  W_v * mu,
                "miter_d":      miter_d * mu,
                "stub_r":       stub_len * mu,
                "stub_ang":     stub_angle * 2,
                "x_cross":      (feed_cross_x -
                                 ((L + cav_left - m_back) / 2)) * mu,
                "y_run":        (y_run if feed_side == "left"
                                 else -board_wid / 2) * mu,
                "x_sma":        ((cav_left - m_back) -
                                 ((L + cav_left - m_back) / 2)) * mu,
                "port_margin":  1.5 * feed["W"] * mu,
            }),
            "cst_full_model_macro": self._build_cst_full_model_macro(
                feed_side, full_model_defaults),
            "cst_recipe_steps": [
                "TOP LAYER (slot in the ground plane)",
                "1) Build the ground-plane copper rectangle of size "
                "board_L × board_W on the TOP face of the substrate, "
                "centred on the origin.",
                "2) Build the four slot-boundary analytical curves above "
                "(upper_taper, lower_taper, aperture_right_edge, "
                "back_cavity_arc).",
                "3) Curves ▸ Join Curves to make one closed loop, then "
                "Cover Curve to make a face.",
                "4) Boolean ▸ Subtract that face from the ground-plane "
                "copper.  The slot+cavity opening is now etched.",
                "",
                "BOTTOM LAYER (microstrip feed + radial stub)",
                "5) RECOMMENDED: File ▸ Export geometry ▸ CST VBA macro… "
                "and paste the resulting macro into CST's History List. "
                "It builds the L-feed polygon (taper + miter) and the "
                "radial-stub sector parametrically from x_cross, W_feed, "
                "feed_w_slot, miter_d, stub_r, stub_ang, then creates "
                "Port 1 from free coordinates at the feed launch. Use that "
                "port instead of picking the feed edge face; face-pick "
                "history is brittle after parameter rebuilds.",
                "6) MANUAL FALLBACK: import the bottom-layer DXF curves "
                "(feed + stub), Cover Curve on each, Union together. Faster "
                "to set up but you'll lose parametric tunability.",
                "",
                "Now sweep any base parameter (L, W_ap, w0, cav_rad, "
                "W_feed, feed_w_slot, miter_d, stub_r, …) and CST re-meshes "
                "automatically. center_x updates via L − board_L/2 so the "
                "curves stay on the board.",
            ],
        }

    def _build_cst_vba_macro(self, feed_side: str,
                              defaults: dict | None = None) -> str:
        """Return a CST VBA macro that builds the bottom-layer feed + stub
        parametrically. References CST parameter names so sweeping
        x_cross / W_feed / feed_w_slot / etc. rebuilds the geometry.

        `defaults` is {param_name: numeric_value_in_display_units} — used
        at the top of the macro to call EnsureParam(name, default). Any
        parameter already present in the user's CST project keeps its
        existing value; missing ones are created with the default.

        Uses CST's documented Line + Arc + ExtrudeCurve idiom (see CST's
        built-in 'Construct/Solids/Radial Stub' macro for reference).
        """
        defaults = defaults or {}
        # Order parameters in a sensible "read top-to-bottom" sequence
        # so the new entries make sense in CST's parameter list.
        param_order = [
            ("h",            "Substrate thickness"),
            ("t_cu",         "Copper layer thickness (1 oz default)"),
            ("W_feed",       "Microstrip width, horizontal run"),
            ("feed_w_slot",  "Microstrip width at the slot crossing"),
            ("miter_d",      "Outer L-bend chamfer depth"),
            ("stub_r",       "Radial-stub radius"),
            ("stub_ang",     "Radial-stub full sector angle (deg)"),
            ("x_cross",      "Slot-crossing x (board-centered)"),
            ("y_run",        "Horizontal-run y (board-centered)"),
            ("x_sma",        "SMA pad x (board-centered)"),
            ("port_margin",  "Waveguide-port margin around the launch"),
        ]

        out = []
        out.append("' " + "=" * 70)
        out.append("' Vivaldi bottom-layer feed + radial stub")
        out.append("' Generated by Antenna Designer")
        out.append("' " + "=" * 70)
        out.append("'")
        out.append("' The macro is self-contained — it AUTO-CREATES any missing")
        out.append("' parameters (with the values you exported from the GUI).")
        out.append("' If a parameter already exists in your CST project, your")
        out.append("' value wins. So you can paste-and-run on a blank project,")
        out.append("' OR onto a project where you've already tweaked some of")
        out.append("' the knobs by hand.")
        out.append("'")
        out.append("' Project units MUST match what you exported in (the")
        out.append("' default values below assume the same unit system).")
        out.append("'")
        out.append("' How to run:")
        out.append("'   Macros > Edit/Run VBA Macro... > paste this whole file,")
        out.append("'   click Run.   OR  save as .bas and use Macros > Run Macro.")
        out.append("'")
        out.append("' Tunable knobs (sweep any of these in CST's Parameter List")
        out.append("' after the macro runs and the bottom layer rebuilds):")
        out.append("'   x_cross       - slot-crossing position (balun centre freq)")
        out.append("'   stub_r        - radial-stub radius (virtual-short freq)")
        out.append("'   stub_ang      - sector full angle, deg (balun bandwidth)")
        out.append("'   feed_w_slot   - microstrip width at slot (Z-match)")
        out.append("'   W_feed        - main microstrip width (Z0)")
        out.append("'   miter_d       - corner chamfer (bend compensation)")
        out.append("'   port_margin   - extra waveguide-port clearance around launch")
        out.append("'")
        out.append("")
        out.append("Sub Main ()")
        out.append("")
        out.append("' " + "=" * 60)
        out.append("' VERTICAL PLACEMENT — set at runtime via dialog")
        out.append("' " + "=" * 60)
        out.append("'")
        out.append("' A dialog pops up so you can type the expression that gives")
        out.append("' the z-coordinate where the TOP face of the bottom copper sits.")
        out.append("' The copper extrudes DOWNWARD by t_cu from there.")
        out.append("'")
        out.append("' To skip the prompt on future runs, just hard-code the line")
        out.append("' Z_FEED_TOP = \"...\" with whatever you ended up using.")
        out.append("'")
        out.append("Dim Z_FEED_TOP As String")
        out.append("Dim defaultZ As String")
        out.append("Dim probeMaskH As Double")
        out.append("On Error Resume Next")
        out.append('probeMaskH = RestoreDoubleParameter("mask_h")')
        out.append("If Err.Number = 0 Then")
        out.append('    defaultZ = "mask_h + t_cu"')
        out.append("Else")
        out.append("    Err.Clear")
        out.append('    defaultZ = "-h"')
        out.append("End If")
        out.append("On Error Goto 0")
        out.append("")
        out.append("' Resolve t_cu to a numeric value for ExtrudeCurve.Thickness")
        out.append("' (CST's ExtrudeCurve expects a Double for Thickness, not a")
        out.append("' string expression — passing strings caused the extrude to")
        out.append("' go the wrong direction in earlier macro versions.)")
        out.append("Dim tCuVal As Double")
        out.append('tCuVal = RestoreDoubleParameter("t_cu")')
        out.append("")
        out.append("Z_FEED_TOP = InputBox( _")
        out.append('    "Where should the TOP face of the bottom copper sit?" & vbCrLf & _')
        out.append('    "(The copper then extrudes DOWNWARD by t_cu from there,)" & vbCrLf & _')
        out.append('    "(so its bottom ends up at Z_FEED_TOP - t_cu.)" & vbCrLf & vbCrLf & _')
        out.append('    "Examples (type any CST expression):" & vbCrLf & _')
        out.append('    "   0                 substrate sits at [0, h]" & vbCrLf & _')
        out.append('    "   -h                substrate sits at [-h, 0]" & vbCrLf & _')
        out.append('    "   mask_h            substrate sits at [mask_h, ...]" & vbCrLf & _')
        out.append('    "   mask_h + t_cu     substrate sits at [mask_h+t_cu, ...]" & vbCrLf & vbCrLf & _')
        out.append('    "Tip: it''s the SAME value as the z-coordinate of the bottom face" & vbCrLf & _')
        out.append('    "of your substrate solid. Easy way to check: pick that face in CST.", _')
        out.append('    "Vivaldi - Bottom Copper Placement", _')
        out.append("    defaultZ)")
        out.append("")
        out.append('If Z_FEED_TOP = "" Then')
        out.append('    MsgBox "Cancelled. No copper was built."')
        out.append("    Exit Sub")
        out.append("End If")
        out.append("")
        out.append("' ExtrudeCurve in this CST version places the extruded solid")
        out.append("' with its BOTTOM at the curve plane (not the top), regardless")
        out.append("' of Thickness sign. So to land the copper TOP at Z_FEED_TOP,")
        out.append("' we translate by (Z_FEED_TOP - t_cu).")
        out.append("Dim translateZ As String")
        out.append('translateZ = "(" & Z_FEED_TOP & ") - t_cu"')
        out.append("Dim portZMin As String")
        out.append("Dim portZMax As String")
        out.append('portZMin = "(" & Z_FEED_TOP & ") - t_cu"')
        out.append('portZMax = "(" & Z_FEED_TOP & ") + h"')
        out.append("")
        out.append("' --- Ensure feed/stub geometry parameters exist (idempotent")
        out.append("'     — won't clobber any value you've already entered) ---")
        for name, comment in param_order:
            if name not in defaults:
                continue
            val = defaults[name]
            out.append(f'EnsureParam "{name}", {val:.6g}   \' {comment}')
        out.append("")
        out.append("WCS.ActivateWCS \"global\"")
        out.append("")

        # ============================================================
        # 1. Combined feed + stub as ONE closed polygon
        # ============================================================
        # The stub's apex line is REPLACED by the arc + two radial sides
        # in the combined boundary, so the feed and stub form a single
        # closed contour with no shared internal edge (which was creating
        # a degenerate face that broke port picking after Boolean Add).
        #
        # Each "segment" is either a Line (4-tuple of expressions
        # x1, y1, x2, y2) or the marker "ARC" (handled specially below).
        arc_L_x = "x_cross + stub_r*cos((90 + stub_ang/2)*pi/180)"
        arc_L_y = "stub_r*sin((90 + stub_ang/2)*pi/180)"
        arc_R_x = "x_cross + stub_r*cos((90 - stub_ang/2)*pi/180)"
        arc_R_y = "stub_r*sin((90 - stub_ang/2)*pi/180)"

        if feed_side == "left":
            segments = [
                # (kind, x1, y1, x2, y2)
                ("Line", "x_sma",                   "y_run + W_feed/2",
                         "x_cross - W_feed/2",      "y_run + W_feed/2"),       # top edge
                ("Line", "x_cross - W_feed/2",      "y_run + W_feed/2",
                         "x_cross - feed_w_slot/2", "0"),                       # taper L
                ("Line", "x_cross - feed_w_slot/2", "0",
                         arc_L_x,                   arc_L_y),                   # stub side L
                ("Arc",  arc_L_x, arc_L_y, arc_R_x, arc_R_y),                   # arc CW over top
                ("Line", arc_R_x,                   arc_R_y,
                         "x_cross + feed_w_slot/2", "0"),                       # stub side R
                ("Line", "x_cross + feed_w_slot/2", "0",
                         "x_cross + W_feed/2",      "y_run + W_feed/2"),        # taper R
                ("Line", "x_cross + W_feed/2",      "y_run + W_feed/2",
                         "x_cross + W_feed/2",      "y_run - W_feed/2 + miter_d"),# vert down
                ("Line", "x_cross + W_feed/2",      "y_run - W_feed/2 + miter_d",
                         "x_cross + W_feed/2 - miter_d", "y_run - W_feed/2"),   # miter
                ("Line", "x_cross + W_feed/2 - miter_d", "y_run - W_feed/2",
                         "x_sma",                   "y_run - W_feed/2"),        # bottom edge
                ("Line", "x_sma",                   "y_run - W_feed/2",
                         "x_sma",                   "y_run + W_feed/2"),        # SMA left
            ]
        else:
            # bottom-feed: tapered trapezoid with stub at slot crossing
            segments = [
                ("Line", "x_cross - W_feed/2",      "y_run",
                         "x_cross - feed_w_slot/2", "0"),
                ("Line", "x_cross - feed_w_slot/2", "0",
                         arc_L_x,                   arc_L_y),
                ("Arc",  arc_L_x, arc_L_y, arc_R_x, arc_R_y),
                ("Line", arc_R_x,                   arc_R_y,
                         "x_cross + feed_w_slot/2", "0"),
                ("Line", "x_cross + feed_w_slot/2", "0",
                         "x_cross + W_feed/2",      "y_run"),
                ("Line", "x_cross + W_feed/2",      "y_run",
                         "x_cross - W_feed/2",      "y_run"),
            ]

        out.append("' " + "=" * 60)
        out.append("' 1. Combined feed + stub closed polygon (single curve)")
        out.append("' " + "=" * 60)
        out.append("")

        for i, seg in enumerate(segments):
            kind = seg[0]
            if kind == "Line":
                _, x1, y1, x2, y2 = seg
                out.append("With Line")
                out.append("     .Reset")
                out.append(f'     .Name "fs_s{i+1}"')
                out.append('     .Curve "vivaldi_bottom_outline"')
                out.append(f'     .X1 "{x1}"')
                out.append(f'     .Y1 "{y1}"')
                out.append(f'     .X2 "{x2}"')
                out.append(f'     .Y2 "{y2}"')
                out.append("     .Create")
                out.append("End With")
                out.append("")
            else:  # Arc
                _, x1, y1, x2, y2 = seg
                out.append("With Arc")
                out.append("     .Reset")
                out.append(f'     .Name "fs_s{i+1}"')
                out.append('     .Curve "vivaldi_bottom_outline"')
                out.append('     .Orientation "Clockwise"')
                out.append('     .XCenter "x_cross"')
                out.append('     .YCenter "0"')
                out.append(f'     .X1 "{x1}"')
                out.append(f'     .Y1 "{y1}"')
                out.append('     .Angle "stub_ang"')
                out.append('     .UseAngle "True"')
                out.append('     .Segments "0"')
                out.append("     .Create")
                out.append("End With")
                out.append("")

        out.append("' Extrude the closed loop into a thin copper solid")
        out.append("' Keep DeleteProfile False so the source curve survives —")
        out.append("' some CST tools (port extension calc, in particular) need")
        out.append("' the original curve in the navigation tree for downstream ops.")
        out.append("With ExtrudeCurve")
        out.append("     .Reset")
        out.append('     .Name "vivaldi_feed"')
        out.append('     .Component "component1"')
        out.append('     .Material "PEC"')
        out.append("     .Thickness -tCuVal")
        out.append('     .Twistangle "0.0"')
        out.append('     .Taperangle "0.0"')
        out.append('     .DeleteProfile "False"')
        out.append('     .Curve "vivaldi_bottom_outline:fs_s1"')
        out.append("     .Create")
        out.append("End With")
        out.append("")
        out.append("' Translate so the copper TOP face sits at Z_FEED_TOP")
        out.append("With Transform")
        out.append("     .Reset")
        out.append('     .Name "component1:vivaldi_feed"')
        out.append('     .Vector "0", "0", translateZ')
        out.append('     .UsePickedPoints "False"')
        out.append('     .InvertPickedPoints "False"')
        out.append('     .MultipleObjects "False"')
        out.append('     .GroupObjects "False"')
        out.append('     .Repetitions "1"')
        out.append('     .MultipleSelection "False"')
        out.append("     .Transform \"Shape\", \"Translate\"")
        out.append("End With")
        out.append("")
        out.append("' Create Port 1 from free coordinates at the feed launch.")
        out.append("' This avoids CST history entries that depend on a picked")
        out.append("' solid face ID; those face IDs can change when the feed")
        out.append("' rebuilds during port-extension or parameter sweeps.")
        out.append("On Error Resume Next")
        out.append('Port.Delete "1"')
        out.append("On Error Goto 0")
        out.append("With Port")
        out.append("     .Reset")
        out.append('     .PortNumber "1"')
        out.append('     .Label "vivaldi_feed"')
        out.append('     .Folder ""')
        out.append('     .NumberOfModes "1"')
        out.append('     .AdjustPolarization "False"')
        out.append('     .PolarizationAngle "0.0"')
        out.append('     .ReferencePlaneDistance "0"')
        out.append('     .TextSize "50"')
        out.append('     .TextMaxLimit "0"')
        out.append('     .Coordinates "Free"')
        if feed_side == "left":
            out.append('     .Orientation "xmin"')
            out.append('     .Xrange "x_sma", "x_sma"')
            out.append('     .Yrange "y_run - W_feed/2", "y_run + W_feed/2"')
        else:
            out.append('     .Orientation "ymin"')
            out.append('     .Xrange "x_cross - W_feed/2", "x_cross + W_feed/2"')
            out.append('     .Yrange "y_run", "y_run"')
        out.append("     .Zrange portZMin, portZMax")
        out.append('     .XrangeAdd "0.0", "0.0"')
        out.append('     .YrangeAdd "0.0", "0.0"')
        out.append('     .ZrangeAdd "0.0", "0.0"')
        out.append('     .SingleEnded "False"')
        out.append('     .WaveguideMonitor "False"')
        out.append("     .Create")
        out.append("End With")
        out.append("")
        out.append("End Sub")
        out.append("")
        out.append("' --- helper: create parameter only if it doesn't exist yet ---")
        out.append("Sub EnsureParam(pname As String, pdefault As Double)")
        out.append("    On Error Resume Next")
        out.append("    Dim v As Double")
        out.append("    v = RestoreDoubleParameter(pname)")
        out.append("    If Err.Number <> 0 Then")
        out.append("        Err.Clear")
        out.append("        StoreDoubleParameter pname, pdefault")
        out.append("    End If")
        out.append("    On Error Goto 0")
        out.append("End Sub")
        return "\n".join(out) + "\n"

    def _build_cst_full_model_macro(self, feed_side: str,
                                    defaults: dict | None = None) -> str:
        """Build the complete Vivaldi CST model as parameterized history.

        This is the preferred CST path for tuning: the board, copper, slot,
        bottom feed/stub, and port are all created from Parameter List names
        rather than imported as static DXF/STEP geometry.
        """
        defaults = defaults or {}

        def put_param(lines, name):
            if name in defaults:
                lines.append(f'    StoreDoubleParameter "{name}", {defaults[name]:.12g}')

        def brick(lines, name, material, xr, yr, zr):
            lines += [
                "With Brick",
                "     .Reset",
                f'     .Name "{name}"',
                '     .Component "Vivaldi"',
                f'     .Material "{material}"',
                f'     .Xrange "{xr[0]}", "{xr[1]}"',
                f'     .Yrange "{yr[0]}", "{yr[1]}"',
                f'     .Zrange "{zr[0]}", "{zr[1]}"',
                "     .Create",
                "End With",
                "",
            ]

        unit = "mil" if defaults.get("_unit") == "mils" else "mm"
        # Build a parameterized polygon for the whole slot+cavity opening:
        # upper taper -> aperture edge -> lower taper -> back cavity arc.
        # CST's Polygon object rejects function-heavy point expressions in
        # some versions, so keep point coordinates to arithmetic on Parameter
        # List variables plus numeric shape coefficients generated here.
        n_taper = 34
        n_cavity = 40
        slot_points = []
        w0_default = float(defaults.get("w0", 1.0))
        W_ap_default = float(defaults.get("W_ap", max(w0_default * 2, 2.0)))
        cav_rad_default = float(defaults.get("cav_rad", max(w0_default, 1.0)))
        taper_denom = max(W_ap_default / 2 - w0_default / 2, 1e-12)
        for i in range(n_taper):
            q = i / (n_taper - 1)
            x = f"({q:.12g})*L - center_x"
            y_default = (w0_default / 2) * np.exp(
                np.log(W_ap_default / w0_default) * q)
            y_shape = (y_default - w0_default / 2) / taper_denom
            y = f"(w0/2) + ({y_shape:.12g})*(W_ap/2 - w0/2)"
            slot_points.append((x, y))
        for i in range(n_taper - 1, -1, -1):
            q = i / (n_taper - 1)
            x = f"({q:.12g})*L - center_x"
            y_default = (w0_default / 2) * np.exp(
                np.log(W_ap_default / w0_default) * q)
            y_shape = (y_default - w0_default / 2) / taper_denom
            y = f"-((w0/2) + ({y_shape:.12g})*(W_ap/2 - w0/2))"
            slot_points.append((x, y))
        a0_default = np.arcsin(min(max(w0_default / (2 * cav_rad_default),
                                      -0.999999), 0.999999))
        cav_cx_norm = -np.sqrt(
            max(cav_rad_default ** 2 - (w0_default / 2) ** 2, 0.0)
        ) / cav_rad_default
        for i in range(n_cavity):
            q = i / (n_cavity - 1)
            if i == 0:
                x = "-center_x"
                y = "-w0/2"
            elif i == n_cavity - 1:
                x = "-center_x"
                y = "w0/2"
            else:
                t = -a0_default - q * (2 * np.pi - 2 * a0_default)
                x = f"({cav_cx_norm + np.cos(t):.12g})*cav_rad - center_x"
                y = f"({np.sin(t):.12g})*cav_rad"
            slot_points.append((x, y))
        upper_slot = slot_points[:n_taper]
        lower_slot = slot_points[n_taper:2 * n_taper]
        cavity_slot = slot_points[2 * n_taper:]
        top_copper_points = [
            ("board_L/2", "W_ap/2"),
            ("board_L/2", "board_W/2"),
            ("-board_L/2", "board_W/2"),
            ("-board_L/2", "-board_W/2"),
            ("board_L/2", "-board_W/2"),
            ("board_L/2", "-W_ap/2"),
        ]
        top_copper_points.extend(lower_slot[1:])
        top_copper_points.extend(cavity_slot[1:])
        top_copper_points.extend(upper_slot[1:])

        arc_L_x = "x_cross + stub_r*cos((90 + stub_ang/2)*pi/180)"
        arc_L_y = "stub_r*sin((90 + stub_ang/2)*pi/180)"
        arc_R_x = "x_cross + stub_r*cos((90 - stub_ang/2)*pi/180)"
        arc_R_y = "stub_r*sin((90 - stub_ang/2)*pi/180)"
        stub_ang_default = float(defaults.get("stub_ang", 90.0))
        stub_arc = []
        for q in (i / 23 for i in range(24)):
            theta = np.deg2rad(90 + stub_ang_default / 2 - q * stub_ang_default)
            stub_arc.append((
                f"x_cross + ({np.cos(theta):.12g})*stub_r",
                f"({np.sin(theta):.12g})*stub_r",
            ))
        if feed_side == "left":
            feed_points = [
                ("x_sma", "y_run + W_feed/2"),
                ("x_cross - W_feed/2", "y_run + W_feed/2"),
                ("x_cross - feed_w_slot/2", "0"),
                *stub_arc,
                ("x_cross + feed_w_slot/2", "0"),
                ("x_cross + W_feed/2", "y_run + W_feed/2"),
                ("x_cross + W_feed/2", "y_run - W_feed/2 + miter_d"),
                ("x_cross + W_feed/2 - miter_d", "y_run - W_feed/2"),
                ("x_sma", "y_run - W_feed/2"),
            ]
        else:
            feed_points = [
                ("x_cross - W_feed/2", "y_run"),
                ("x_cross - feed_w_slot/2", "0"),
                *stub_arc,
                ("x_cross + feed_w_slot/2", "0"),
                ("x_cross + W_feed/2", "y_run"),
            ]

        out = [
            "' Full tunable CST model: Vivaldi Exponential TSA",
            "' Generated by Antenna Designer",
            "' Edit Parameter List values in CST, then Rebuild to retune.",
            "",
            "Sub Main ()",
            "    With Units",
            f'        .Geometry "{unit}"',
            '        .Frequency "GHz"',
            '        .Time "ns"',
            '        .TemperatureUnit "Kelvin"',
            "    End With",
            "",
            "    ' Parameter List values",
        ]
        for name in (
            "fr_GHz", "f_low_GHz", "f_high_GHz", "er", "tan_d",
            "L", "W_ap", "w0", "cav_rad", "h", "t_cu", "W_feed",
            "feed_w_slot", "miter_d", "stub_r", "stub_ang", "m_back",
            "m_side", "board_L", "board_W", "center_x", "x_cross",
            "y_run", "x_sma", "port_margin", "port_k",
        ):
            put_param(out, name)
        out += [
            "",
            '    Solver.FrequencyRange "f_low_GHz", "f_high_GHz"',
            "",
            "With Material",
            "     .Reset",
            '     .Name "Antenna_Substrate"',
            '     .Type "Normal"',
            '     .Epsilon "er"',
            '     .Mue "1.0"',
            '     .TanD "tan_d"',
            "     .Create",
            "End With",
            "",
        ]
        brick(out, "Substrate", "Antenna_Substrate",
              ("-board_L/2", "board_L/2"),
              ("-board_W/2", "board_W/2"),
              ("-h", "0"))

        out += [
            "' Top copper is generated as the final copper outline.",
            "' This avoids fragile curve-solid Boolean subtraction in CST.",
            "With Polygon",
            "     .Reset",
            '     .Name "Top_Copper_Profile"',
            '     .Curve "vivaldi_top_outline"',
        ]
        x0, y0 = top_copper_points[0]
        out.append(f'     .Point "{x0}", "{y0}"')
        for x, y in top_copper_points[1:]:
            out.append(f'     .LineTo "{x}", "{y}"')
        out.append(f'     .LineTo "{x0}", "{y0}"')
        out += [
            "     .Create",
            "End With",
            "",
            "With CoverCurve",
            "     .Reset",
            '     .Name "Top_Copper_Face"',
            '     .Component "Vivaldi"',
            '     .Material "PEC"',
            '     .Curve "vivaldi_top_outline:Top_Copper_Profile"',
            '     .DeleteCurve "False"',
            "     .Create",
            "End With",
            "With ExtrudeCurve",
            "     .Reset",
            '     .Name "Top_Copper"',
            '     .Component "Vivaldi"',
            '     .Material "PEC"',
            '     .Thickness "t_cu"',
            '     .Twistangle "0.0"',
            '     .Taperangle "0.0"',
            '     .DeleteProfile "False"',
            '     .Curve "vivaldi_top_outline:Top_Copper_Profile"',
            "     .Create",
            "End With",
            "",
            "' Bottom feed and radial stub as one closed curve",
            "With Polygon",
            "     .Reset",
            '     .Name "Bottom_Feed_Profile"',
            '     .Curve "vivaldi_bottom_outline"',
        ]
        x0, y0 = feed_points[0]
        out.append(f'     .Point "{x0}", "{y0}"')
        for x, y in feed_points[1:]:
            out.append(f'     .LineTo "{x}", "{y}"')
        out.append(f'     .LineTo "{x0}", "{y0}"')
        out += [
            "     .Create",
            "End With",
            "With ExtrudeCurve",
            "     .Reset",
            '     .Name "Bottom_Feed"',
            '     .Component "Vivaldi"',
            '     .Material "PEC"',
            '     .Thickness "t_cu"',
            '     .Twistangle "0.0"',
            '     .Taperangle "0.0"',
            '     .DeleteProfile "True"',
            '     .Curve "vivaldi_bottom_outline:Bottom_Feed_Profile"',
            "     .Create",
            "End With",
            "With Transform",
            "     .Reset",
            '     .Name "Vivaldi:Bottom_Feed"',
            '     .Vector "0", "0", "-h - t_cu"',
            '     .UsePickedPoints "False"',
            '     .Repetitions "1"',
            '     .MultipleObjects "False"',
            '     .Transform "Shape", "Translate"',
            "End With",
            "",
            "On Error Resume Next",
            'Port.Delete "1"',
            "On Error Goto 0",
            "' Leave the real feed edge picked for CST's built-in",
            "' Solver > Ports > Calculate Port Extension Coefficient macro.",
            "' That calculator should construct the waveguide port because",
            "' the extension coefficient depends on W_feed, h, er, and fmax.",
            'Pick.PickFaceFromId "Vivaldi:Bottom_Feed", "7"',
        ]
        if defaults.get("port_k") is not None:
            out += [
                "' Port constructed using CST's bundled microstrip extension",
                "' tables (same 1% error tables used by the solver macro).",
                "With Port",
                "     .Reset",
                '     .PortNumber "1"',
                '     .Label "vivaldi_feed"',
                '     .NumberOfModes "1"',
                '     .AdjustPolarization False',
                '     .PolarizationAngle "0.0"',
                '     .ReferencePlaneDistance "0"',
                '     .TextSize "50"',
                '     .Coordinates "Picks"',
                '     .Orientation "Positive"',
                '     .PortOnBound "True"',
                '     .ClipPickedPortToBound "False"',
            ]
            if feed_side == "left":
                out += [
                    '     .XrangeAdd "0", "0"',
                    '     .YrangeAdd "h*port_k", "h*port_k"',
                    '     .ZrangeAdd "h*port_k", "h"',
                ]
            else:
                out += [
                    '     .XrangeAdd "h*port_k", "h*port_k"',
                    '     .YrangeAdd "0", "0"',
                    '     .ZrangeAdd "h*port_k", "h"',
                ]
            out += [
                '     .Shield "PEC"',
                '     .SingleEnded "False"',
                "     .Create",
                "End With",
            ]
        out += [
            "",
            "End Sub",
            "",
        ]
        return "\n".join(out)

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        gain_dbi = 8 + 2 * np.log10(max(r["L"] * ctx.fr / C_LIGHT, 0.2))
        out = [
            f"  Band              = {r['f_low']/1e9:.2f}–{r['f_high']/1e9:.2f} GHz",
            f"  Taper length L    = {r['L']*m:.2f} {u}  ({r['L']*r['f_low']/C_LIGHT:.2f} λ_low)",
            f"  Aperture W_ap     = {r['W_ap']*m:.2f} {u}  ({r['W_ap']/(0.5*C_LIGHT/r['f_low']):.2f}·λ_low/2)",
            f"  Throat w₀         = {r['w0']*m:.3f} {u}",
            f"  Taper rate R      = {r['R_rate']/m:.4f} / {u}",
            f"  Back-cavity Ø     = {r['cavity_dia']*m:.2f} {u}",
            "",
            f"  Feed ↦ slotline   = {r['feed_cross_x']*m:.2f} {u} from cavity  (λ_g_slot/4 @ fr)",
            f"  Slot W @ crossing = {r['slot_w_feed']*m:.3f} {u}  (slotline width the feed taps)",
            f"  Microstrip W      = {r['W_feed']*m:.3f} {u}  (Z₀={r['feed_Z']:.0f} Ω, εr_eff={r['Ereff_feed']:.2f})",
            f"  Microstrip run    ≈ {r['feed_len']*m:.2f} {u}  (SMA → slot crossing, {r['feed_side']} feed)",
            f"  Radial stub       = r={r['stub_len']*m:.2f} {u}  ({r['stub_angle_deg']:.0f}° sector)",
            "",
            f"  Estimated gain    ≈ {gain_dbi:.1f} dBi (typical)",
        ]
        if r.get("warnings"):
            out.append("")
            out += [f"  ⚠ {w}" for w in r["warnings"]]
        return out

    def _taper_points(self, r, m, N=120):
        """Upper taper profile in display units (x from 0→L, y = slot half-width)."""
        L  = r["L"] * m
        w0 = r["w0"] * m
        W_ap = r["W_ap"] * m
        Rm = r["R_rate"] / m      # convert 1/m → 1 / display-unit
        x = np.linspace(0, L, N)
        y = (w0 / 2) * np.exp(Rm * x)
        y = np.minimum(y, W_ap / 2)
        return np.column_stack([x, y])

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L    = r["L"] * m
        W_ap = r["W_ap"] * m
        w0   = r["w0"] * m
        cav_r = 0.5 * r["cavity_dia"] * m
        mb   = r["m_back"] * m
        ms   = r["m_side"] * m
        wf   = r["W_feed"] * m
        stub_len   = r["stub_len"] * m
        stub_half  = np.radians(r["stub_angle_deg"])
        feed_x     = r["feed_cross_x"] * m

        style_ax(ax.figure, ax, "Vivaldi — Exponentially Tapered Slot", equal=True)

        # Board footprint: x from (cavity-leftmost − m_back) to (+L — aperture
        # opens flush with the right board edge). Cavity centre comes from
        # compute() (it's chosen so the cavity passes through (0, ±w0/2)).
        if cav_r > w0/2:
            _cx_off = float(np.sqrt(cav_r ** 2 - (w0/2) ** 2))
        else:
            _cx_off = cav_r
        x_left  = -_cx_off - cav_r - mb
        x_right = L                                   # aperture at board edge
        y_half  = W_ap / 2 + ms
        ax.add_patch(mpatches.Rectangle(
            (x_left, -y_half), x_right - x_left, 2 * y_half,
            facecolor=LAYER_COLORS["substrate"],
            edgecolor=LAYER_COLORS["axis"], lw=0.7, zorder=1))

        # ---- Top copper (ground plane with exponential slot + back cavity hole) ----
        upper = self._taper_points(r, m)

        # Outer board rectangle (CCW)
        outer = [
            (x_left, -y_half), (x_right, -y_half),
            (x_right,  y_half), (x_left,  y_half),
        ]

        # Hole = back-cavity circle ∪ exponential slot, traversed clockwise.
        # Cavity centre chosen so the cavity passes EXACTLY through the throat
        # points (0, ±w0/2) — no gap between cavity and tapers.
        cav_cx = -_cx_off
        ang = np.linspace(-np.pi, np.pi, 120)
        cav_arc = [(cav_cx + cav_r * np.cos(a), cav_r * np.sin(a)) for a in ang]

        # The throat meets the cavity at (0, ±w0/2). On the cavity circle centered
        # at (cav_cx, 0), those points sit at angles ±a0.
        if cav_r > 0 and w0 > 0 and cav_r > w0/2:
            a0 = np.arcsin((w0/2) / cav_r)
        else:
            a0 = 0.0

        # Path traversal (one continuous closed loop so even-odd fill carves the hole):
        #   (0,+w0/2) →  along upper taper to (L,+y_m)
        #            →  down aperture to (L,-y_m)
        #            →  along lower taper back to (0,-w0/2)
        #            →  CW around cavity back (angle -a0 → a0-2π) to (0,+w0/2)
        upper_pts = upper.tolist()
        lower_pts = [(xx, -yy) for xx, yy in reversed(upper_pts)]

        ang_cav = np.linspace(-a0, a0 - 2*np.pi, 120)
        cav_path = [(cav_cx + cav_r * np.cos(a), cav_r * np.sin(a)) for a in ang_cav]

        hole = []
        hole += upper_pts                                        # (0,+w0/2)→(L,+y_m)
        hole += [(L, upper_pts[-1][1]), (L, -upper_pts[-1][1])]  # aperture edge
        hole += lower_pts                                        # (L,-y_m)→(0,-w0/2)
        hole += cav_path                                         # back cavity arc
        hole += [upper_pts[0]]

        verts = outer + [outer[0]] + hole + [hole[0]]
        codes = ([MPath.MOVETO] + [MPath.LINETO]*3 + [MPath.CLOSEPOLY]
                 + [MPath.MOVETO] + [MPath.LINETO]*(len(hole)-1) + [MPath.CLOSEPOLY])
        # length check; rebuild verts to match codes
        outer_seg = outer + [outer[0]]
        hole_seg  = hole  + [hole[0]]
        codes = ([MPath.MOVETO] + [MPath.LINETO]*(len(outer_seg)-2) + [MPath.CLOSEPOLY]
                 + [MPath.MOVETO] + [MPath.LINETO]*(len(hole_seg) -2) + [MPath.CLOSEPOLY])
        path = MPath(outer_seg + hole_seg, codes)
        ax.add_patch(mpatches.PathPatch(
            path, facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.7, zorder=2))

        # ---- Bottom-side microstrip feed (dashed cyan) ----
        # Feed must cross the slotline PERPENDICULARLY at x = feed_x.  The SMA
        # connector can sit on either the left edge (L-turn bottom trace) or
        # the bottom edge (straight vertical trace).  Slot runs horizontally,
        # so the crossing segment is always vertical.
        feed_side = r.get("feed_side", "left")
        y_bot = -y_half
        y_run = -y_half * 0.55            # where the horizontal run sits
        sma_r = min(wf * 2.0, ms * 0.6)

        # Radial stub sector (same on both layouts) — opens upward from
        # crossing. Apex is a finite W_v-wide segment matching the
        # microstrip top edge so the stub shares an actual edge with the
        # feed (no point-contact). W_v isn't in display units yet so
        # pull from results in metres and convert.
        Wv_disp = r.get("feed_w_slot", 0.0) * m
        if Wv_disp <= 0:
            Wv_disp = wf       # fall back to W_feed if not tapered
        theta_c = np.pi / 2
        ang_s = np.linspace(theta_c - stub_half, theta_c + stub_half, 60)
        stub_pts  = [(feed_x + Wv_disp / 2, 0.0)]
        stub_pts += [(feed_x + stub_len * np.cos(a), stub_len * np.sin(a))
                     for a in ang_s]
        stub_pts.append((feed_x - Wv_disp / 2, 0.0))

        # Filled L-shaped microstrip polygon (with taper + miter). The
        # vertex list was computed by compute() in metres — pull it out and
        # convert to display units here.
        feed_pts_disp = [(px * m, py * m) for px, py in r.get("feed_poly", [])]
        if feed_pts_disp:
            ax.add_patch(mpatches.Polygon(
                feed_pts_disp, closed=True,
                facecolor="#1de9ff66", edgecolor="#1de9ff", lw=1.2,
                ls="--", zorder=4))
        if feed_side == "left":
            ax.add_patch(mpatches.Circle((x_left, y_run), sma_r,
                                         fill=False, ls=":", ec="#1de9ff",
                                         lw=1.0, zorder=4))
            ax.text(x_left, y_run - sma_r*1.4, "SMA", color="#1de9ff",
                    ha="center", va="top", fontsize=8, zorder=5)
        else:  # "bottom"
            ax.add_patch(mpatches.Circle((feed_x, y_bot), sma_r,
                                         fill=False, ls=":", ec="#1de9ff",
                                         lw=1.0, zorder=4))
            ax.text(feed_x + sma_r*1.4, y_bot, "SMA", color="#1de9ff",
                    ha="left", va="center", fontsize=8, zorder=5)

        ax.add_patch(mpatches.Polygon(
            stub_pts, closed=True, facecolor="#1de9ff22",
            edgecolor="#1de9ff", lw=1.1, ls="--", zorder=4))

        # ---- Dimensions ----
        # Overall board outline (drawn first, furthest out)
        dim_horizontal(ax, x_left, x_right, -y_half - ms*0.95,
                       f"Board L = {x_right - x_left:.2f}", offset=0,
                       color=LAYER_COLORS["dim_special"])
        dim_vertical(ax, -y_half, y_half, x_left - mb*0.45,
                     f"Board W = {2*y_half:.2f}", offset=0,
                     color=LAYER_COLORS["dim_special"])
        # Taper envelope
        dim_horizontal(ax, 0, L, -y_half - ms*0.25, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -W_ap/2, W_ap/2, L + ms*0.3,
                     f"W_ap = {W_ap:.2f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        dim_vertical(ax, -w0/2, w0/2, -2*cav_r - mb*0.3,
                     f"w₀ = {w0:.3f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        # Back-cavity size + its offset from the board edge
        leader(ax, (cav_cx, cav_r),
               (cav_cx - cav_r*0.4, y_half - ms*0.2),
               f"Back cavity Ø{2*cav_r:.2f}")
        dim_horizontal(ax, x_left, -2 * cav_r, -y_half + ms*0.25,
                       f"m_back={mb:.2f}", offset=0,
                       color=LAYER_COLORS["dim_alt"])

        # ---- Back-copper (microstrip feed) dimensions ----
        cy = "#1de9ff"
        if feed_side == "left":
            # 1) Horizontal run length (SMA to T-corner)  — along y_run, below slot
            dim_horizontal(ax, x_left, feed_x, y_run - ms*0.35,
                           f"L_run={feed_x - x_left:.2f}",
                           offset=0, color=cy)
            # 2) Vertical rise (T-corner up to slotline crossing)
            dim_vertical(ax, y_run, 0.0, feed_x - ms*0.35,
                         f"L_rise={-y_run:.2f}",
                         offset=0, color=cy)
        else:
            # Bottom-feed: single vertical trace from y_bot up to the slot
            dim_vertical(ax, y_bot, 0.0, feed_x + ms*0.35,
                         f"L_rise={-y_bot:.2f}",
                         offset=0, color=cy)

        # 4) Microstrip linewidth leader (W_feed) — anchor to the trace
        if feed_side == "left":
            leader(ax, (x_left + (feed_x - x_left)*0.35, y_run),
                   (x_left + (feed_x - x_left)*0.35, y_run + ms*0.5),
                   f"W_feed={wf:.2f}")
        else:
            leader(ax, (feed_x, y_bot + (0.0 - y_bot)*0.55),
                   (feed_x + ms*1.0, y_bot + (0.0 - y_bot)*0.35),
                   f"W_feed={wf:.2f}")

        # 5) Radial stub — length and FULL sector angle
        stub_full_deg = 2 * r["stub_angle_deg"]
        leader(ax, (feed_x + stub_len*0.7, stub_len*0.4),
               (feed_x + L*0.25, y_half*0.7),
               f"Radial stub\nr = {stub_len:.2f}\n"
               f"sector = {stub_full_deg:.0f}°")

        # 6) Feed cross (λ_g_slot/4 from cavity throat) — re-anchored
        leader(ax, (feed_x, 0.0),
               (feed_x - L*0.12, -y_half*0.25),
               f"x_cross = {feed_x:.2f}\n(λ_g_slot/4)")

        add_layer_legend(ax, [
            (LAYER_COLORS["copper"],    "Top copper (ground)"),
            (LAYER_COLORS["substrate"], "Slot / cavity (air)"),
            ("#1de9ff",                 "Microstrip feed (bottom)"),
        ], loc="lower right")
        ax.margins(0.08)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "Vivaldi — Slot Width & |E| Along Taper",
                 equal=False, grid=True)
        m = ctx.out_mult
        L    = r["L"] * m
        w0   = r["w0"] * m
        W_ap = r["W_ap"] * m
        Rm = r["R_rate"] / m
        x = np.linspace(0, L, 400)
        slot_w = np.minimum(w0 * np.exp(Rm * x), W_ap)
        E = 1.0 / np.clip(slot_w, 1e-9, None)
        E /= E.max()

        ax.plot(x, slot_w, color="#ffc14a", lw=2, label="Slot width (taper)")
        ax2 = ax.twinx()
        ax2.plot(x, E, color="#00FFCC", lw=2, label="|E| ∝ 1/slot_w")
        ax2.tick_params(colors=LAYER_COLORS["text"])
        ax.set_xlabel(f"x ({ctx.unit_str})", color=LAYER_COLORS["text"])
        ax.set_ylabel(f"slot width ({ctx.unit_str})", color="#ffc14a")
        ax2.set_ylabel("|E| normalized", color="#00FFCC")
        ax.legend(loc="upper left", facecolor=LAYER_COLORS["panel_bg"],
                  edgecolor=LAYER_COLORS["axis"], labelcolor=LAYER_COLORS["text"])
        ax2.legend(loc="upper right", facecolor=LAYER_COLORS["panel_bg"],
                   edgecolor=LAYER_COLORS["axis"], labelcolor=LAYER_COLORS["text"])

    def pattern(self, theta, phi, ctx, r):
        # End-fire along +x; sharpness scales with L/λ at design freq.
        L = r["L"]
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        phi_b   = np.broadcast_to(phi,   np.broadcast_shapes(theta.shape, phi.shape))
        cos_ax = np.sin(theta_b) * np.cos(phi_b)
        n_sharp = 2 + 2.5 * (L * ctx.fr / C_LIGHT)
        return np.clip(cos_ax, 0.0, None) ** n_sharp


# ============================================================================
# Pyramidal Horn
# ============================================================================

@register_antenna("Pyramidal Horn", category="Aperture")
class PyramidalHorn(AntennaBase):
    notes = ("WR-style rectangular waveguide flared to aperture (a1, b1). "
             "Optimum design: b1≈√(2λρ1), a1≈√(3λρ2); max gain when phase error ≈ 0.25λ / 0.4λ.")
    polarization = "linear  (E along the b-wall direction, dominant TE10)"
    beam_axis = "end-fire along +X (aperture face)"
    bandwidth_note = "moderate (~30 %, limited by feeding waveguide cutoff)"

    def inputs(self):
        return [
            Input("a_wg", "WG a (broad wall, units)", "22.86",
                  tooltip="WR-90 default (22.86 mm for X-band)"),
            Input("b_wg", "WG b (narrow wall, units)", "10.16"),
            Input("gain_dBi_target", "Target gain (dBi)", "15"),
        ]

    def compute(self, ctx, params):
        a_wg = ctx.m(params.get("a_wg", "22.86"))
        b_wg = ctx.m(params.get("b_wg", "10.16"))
        G_lin = 10 ** (float(params.get("gain_dBi_target", "15")) / 10)
        lam = ctx.lambda0
        # Optimum pyramidal horn (Balanis 13-54):
        # G = (4π / λ²) · εap · a1·b1, with εap ≈ 0.51 (Huygens)
        # a1 · b1 = G · λ² / (4π · εap)
        # With standard optimum: a1 = √(3λρ2), b1 = √(2λρ1), and ρ1 = ρ2 for pyramidal.
        # Simplified direct sizing: start with a1 ≈ √(G)·0.45λ, b1 ≈ √(G)·0.33λ
        a1 = np.sqrt(G_lin) * 0.47 * lam
        b1 = np.sqrt(G_lin) * 0.33 * lam
        # Flare lengths
        rho_e = b1 ** 2 / (2 * lam)
        rho_h = a1 ** 2 / (3 * lam)
        # Axial (physical) length — use E-plane pe = ρe·(1 - b_wg/b1)
        pe = (rho_e) * (1 - b_wg / b1) if b1 > b_wg else 0
        ph = (rho_h) * (1 - a_wg / a1) if a1 > a_wg else 0
        L_ax = (pe + ph) / 2   # pick the average
        return {"a_wg": a_wg, "b_wg": b_wg, "a1": a1, "b1": b1,
                "rho_e": rho_e, "rho_h": rho_h, "L_ax": L_ax,
                "Gain_dBi": 10 * np.log10(G_lin), "Ereff": 1.0,
                "board_center_m": (L_ax / 2, 0.0)}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Target gain       = {r['Gain_dBi']:.1f} dBi",
            f"  WG aperture       = {r['a_wg']*m:.2f} × {r['b_wg']*m:.2f} {u}",
            f"  Horn aperture a1  = {r['a1']*m:.2f} {u}",
            f"  Horn aperture b1  = {r['b1']*m:.2f} {u}",
            f"  ρE (E-plane R)    = {r['rho_e']*m:.2f} {u}",
            f"  ρH (H-plane R)    = {r['rho_h']*m:.2f} {u}",
            f"  Axial length      = {r['L_ax']*m:.2f} {u}",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        a_wg, b_wg = r["a_wg"] * m, r["b_wg"] * m
        a1, b1 = r["a1"] * m, r["b1"] * m
        L_ax = r["L_ax"] * m
        style_ax(ax.figure, ax, "Pyramidal Horn (Top + Side view)", equal=False)

        # Stack two cross-sections on the same axes:
        #   upper  = Top view  (H-plane), centered at y_top
        #   lower  = Side view (E-plane), centered at y_bot
        gap = max(a1, b1) * 0.25
        y_top = +(a1 / 2 + gap)
        y_bot = -(b1 / 2 + gap)

        # Top view (H-plane):  a_wg → a1 along +x
        top_pts = np.array([
            [0, y_top - a_wg/2], [L_ax, y_top - a1/2],
            [L_ax, y_top + a1/2], [0, y_top + a_wg/2],
        ])
        ax.add_patch(mpatches.Polygon(top_pts,
            facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
            lw=0.9, zorder=2, alpha=0.85))
        # Side view (E-plane): b_wg → b1 along +x
        bot_pts = np.array([
            [0, y_bot - b_wg/2], [L_ax, y_bot - b1/2],
            [L_ax, y_bot + b1/2], [0, y_bot + b_wg/2],
        ])
        ax.add_patch(mpatches.Polygon(bot_pts,
            facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
            lw=0.9, zorder=2, alpha=0.85))
        # Centerlines
        ax.plot([-L_ax*0.05, L_ax*1.05], [y_top, y_top],
                color=LAYER_COLORS["text"], lw=0.4, ls=(0, (3, 3)), alpha=0.35)
        ax.plot([-L_ax*0.05, L_ax*1.05], [y_bot, y_bot],
                color=LAYER_COLORS["text"], lw=0.4, ls=(0, (3, 3)), alpha=0.35)

        # Labels for each view
        ax.text(-L_ax*0.02, y_top + a1/2 + gap*0.15, "Top view (H-plane)",
                fontsize=9, color=LAYER_COLORS["text"], ha="left", va="bottom")
        ax.text(-L_ax*0.02, y_bot - b1/2 - gap*0.15, "Side view (E-plane)",
                fontsize=9, color=LAYER_COLORS["text"], ha="left", va="top")

        # Dimensions — aperture heights on the right, waveguide heights on the left
        dim_vertical(ax, y_top - a1/2, y_top + a1/2, L_ax * 1.04,
                     f"a₁ = {a1:.2f}", offset=0, color=LAYER_COLORS["dim_alt"])
        dim_vertical(ax, y_bot - b1/2, y_bot + b1/2, L_ax * 1.04,
                     f"b₁ = {b1:.2f}", offset=0, color=LAYER_COLORS["dim_alt"])
        dim_vertical(ax, y_top - a_wg/2, y_top + a_wg/2, -L_ax * 0.04,
                     f"a = {a_wg:.2f}", offset=0, color=LAYER_COLORS["dim_alt"])
        dim_vertical(ax, y_bot - b_wg/2, y_bot + b_wg/2, -L_ax * 0.04,
                     f"b = {b_wg:.2f}", offset=0, color=LAYER_COLORS["dim_alt"])
        # Axial length beneath the side view
        dim_horizontal(ax, 0, L_ax, y_bot - b1/2 - gap*0.6,
                       f"L = {L_ax:.2f}", offset=0)
        ax.margins(0.18)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "Horn Aperture — TE₁₀ |Ey|", equal=True, grid=False)
        a1, b1 = r["a1"] * ctx.out_mult, r["b1"] * ctx.out_mult
        X, Y = np.meshgrid(np.linspace(-a1/2, a1/2, 200),
                           np.linspace(-b1/2, b1/2, 200))
        E = np.cos(np.pi * X / a1)  # TE10 distribution
        im = ax.contourf(X, Y, np.abs(E), 60, cmap="magma")
        cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=LAYER_COLORS["text"])

    def pattern(self, theta, phi, ctx, r):
        # Uniform aperture with TE10 distribution (Balanis 13-52):
        # F_H(θ) ∝ cos(X)/(1 - (2X/π)²) where X = ka1·sinθ·cosφ/2
        # F_E(θ) ∝ sin(Y)/Y  where Y = kb1·sinθ·sinφ/2
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        phi_b = np.broadcast_to(phi, np.broadcast_shapes(theta.shape, phi.shape))
        X = k0 * r["a1"] * np.sin(theta_b) * np.cos(phi_b) / 2
        Y = k0 * r["b1"] * np.sin(theta_b) * np.sin(phi_b) / 2
        with np.errstate(divide="ignore", invalid="ignore"):
            FH = np.cos(X) / (1 - (2 * X / np.pi) ** 2)
            FE = np.where(np.abs(Y) < 1e-9, 1.0, np.sin(Y) / Y)
        FH = np.where(np.isfinite(FH), FH, 0.5)
        F = np.abs(FH * FE)
        # Above-waveguide hemisphere
        F = F * np.clip(np.cos(theta_b), 0.0, None) ** 0.5
        return F
