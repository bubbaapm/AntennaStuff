"""
Helical, loop, and small-loop antennas.
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches

from .base import AntennaBase, Context, Input, register_antenna, C_LIGHT, ETA0
from plotting.cad import (
    LAYER_COLORS, style_ax, dim_horizontal, dim_vertical, dim_radial,
    leader, add_layer_legend,
)


# ============================================================================
# Axial-mode helical
# ============================================================================

@register_antenna("Axial-Mode Helical", category="Helical/Loop")
class AxialHelical(AntennaBase):
    notes = ("End-fire helical antenna (Kraus). Valid range: 3/4λ ≤ C ≤ 4/3λ, "
             "pitch 12°–14°. Right-hand or left-hand circular polarization.")

    def inputs(self):
        return [
            Input("turns",      "Number of turns N",      "7"),
            Input("pitch_deg",  "Pitch angle α (°)",      "13"),
            Input("wire_r",     "Wire radius (units)",    "1.5"),
            Input("gnd_r_lam",  "Ground-plane radius (λ)","0.75"),
        ]

    def compute(self, ctx, params):
        N = max(3, int(float(params.get("turns", "7"))))
        alpha_deg = float(params.get("pitch_deg", "13"))
        alpha = np.radians(alpha_deg)
        a = float(params.get("wire_r", "1.5")) * 1e-3
        gnd_r = float(params.get("gnd_r_lam", "0.75")) * ctx.lambda0

        C = ctx.lambda0                   # circumference ≈ λ
        D = C / np.pi                     # coil diameter
        S = C * np.tan(alpha)            # pitch
        L_ax = N * S                     # axial length

        # Kraus gain: G ≈ 12 · (C/λ)² · N · (S/λ) dBi
        Cn = C / ctx.lambda0
        Sn = S / ctx.lambda0
        G_lin = 12 * Cn ** 2 * N * Sn
        G_dBi = 10 * np.log10(G_lin) if G_lin > 0 else 0
        # Input impedance (Kraus): R_in ≈ 140 · (C/λ) Ω
        R_in = 140 * Cn
        # HPBW: θHP ≈ 52 / (C/λ · √(N·S/λ))
        hpbw = 52 / (Cn * np.sqrt(N * Sn)) if N * Sn > 0 else 0
        # Validity check
        valid = 0.75 <= Cn <= 1.33 and 12 <= alpha_deg <= 14
        return {"N": N, "alpha_deg": alpha_deg, "a": a,
                "C": C, "D": D, "S": S, "L_ax": L_ax,
                "gnd_r": gnd_r, "R_in": R_in, "Gain_dBi": G_dBi,
                "HPBW_deg": hpbw, "valid_axial_mode": valid}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        valid = "✓" if r["valid_axial_mode"] else "⚠ outside axial-mode range"
        return [
            f"  Turns N         = {r['N']}",
            f"  Pitch α         = {r['alpha_deg']:.1f}°",
            f"  Circumference C = {r['C']*m:.2f} {u}  ({r['C']/ctx.lambda0:.3f} λ) {valid}",
            f"  Diameter D      = {r['D']*m:.2f} {u}",
            f"  Pitch S         = {r['S']*m:.2f} {u}",
            f"  Axial length    = {r['L_ax']*m:.2f} {u}",
            f"  Wire radius     = {r['a']*m:.3f} {u}",
            f"  GND plane rad   = {r['gnd_r']*m:.2f} {u}  (≥ 0.5 λ recommended)",
            f"  R_in ≈          = {r['R_in']:.0f} Ω  (λ/4 taper to 50 Ω typical)",
            f"  Gain (Kraus)    = {r['Gain_dBi']:.1f} dBi",
            f"  HPBW            = {r['HPBW_deg']:.1f}°",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        D = r["D"] * m
        S = r["S"] * m
        N = r["N"]
        L_ax = r["L_ax"] * m
        gnd = r["gnd_r"] * m
        style_ax(ax.figure, ax, "Helical Antenna — Side View", equal=True)
        # Ground plane
        ax.add_patch(mpatches.Rectangle((-gnd, -0.02*L_ax), 2*gnd, 0.02*L_ax,
                                         facecolor="#3c3c3c", zorder=1))
        # Helix projection — plot x vs z with x = D/2·cos(φ), z = φ/(2π)·S
        t = np.linspace(0, 2 * np.pi * N, 600)
        x = (D / 2) * np.cos(t)
        z = (t / (2 * np.pi)) * S
        ax.plot(x, z, color="#ffce4a", lw=2, zorder=2)
        # Feed
        ax.plot([D/2], [0], "o", color="red", markersize=5, zorder=5)
        dim_vertical(ax, 0, L_ax, D/2 + gnd*0.1, f"L = {L_ax:.1f}", offset=0)
        dim_horizontal(ax, -D/2, D/2, L_ax + S*0.5, f"D = {D:.1f}",
                       offset=0, color=LAYER_COLORS["dim_alt"])
        dim_horizontal(ax, -gnd, gnd, -0.04*L_ax, f"GND Ø = {2*gnd:.1f}",
                       offset=0, color=LAYER_COLORS["dim_alt"])
        ax.text(D/2 * 1.3, L_ax * 0.5,
                f"{N} turns\nα = {r['alpha_deg']:.1f}°\nS = {S:.1f}",
                color=LAYER_COLORS["text"], fontsize=9,
                bbox=dict(facecolor=LAYER_COLORS["panel_bg"],
                          edgecolor=LAYER_COLORS["axis"], pad=4))

    def plot_fields(self, ax, ctx, r):
        ax.text(0.5, 0.5, "Helical: circular polarization — see 3D pattern",
                ha="center", va="center", transform=ax.transAxes,
                color=LAYER_COLORS["text"], fontsize=11)
        ax.set_axis_off()

    def pattern(self, theta, phi, ctx, r):
        # Kraus cos^n(θ) axial-mode approximation along +z; beam width set by N, S/λ
        N = r["N"]
        Sn = r["S"] / ctx.lambda0
        Cn = r["C"] / ctx.lambda0
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        psi = 2 * np.pi * Sn * (1 - np.cos(theta_b)) + np.pi / N   # Hansen-Woodyard-ish
        with np.errstate(divide="ignore", invalid="ignore"):
            AF = np.sin(N * psi / 2) / (N * np.sin(psi / 2))
        AF = np.where(np.isnan(AF), 1.0, AF)
        # Element (single loop) factor ≈ cos θ above ground
        elem = np.where(np.cos(theta_b) > 0, np.cos(theta_b), 0)
        return np.abs(AF) * elem


# ============================================================================
# Small / large loop
# ============================================================================

@register_antenna("Circular Loop", category="Helical/Loop")
class CircularLoop(AntennaBase):
    notes = ("Small loop (C ≪ λ): magnetic dipole, Rr = 20π²(C/λ)⁴. "
             "Large loop (C ≈ λ): resonant, high R_in (~100 Ω), single main lobe in plane.")

    def inputs(self):
        return [
            Input("radius", "Loop radius (units)", "10.0"),
            Input("wire_r", "Wire radius (units)", "0.5"),
        ]

    def compute(self, ctx, params):
        a = float(params.get("radius", "10")) * 1e-3
        aw = float(params.get("wire_r", "0.5")) * 1e-3
        C = 2 * np.pi * a
        Cn = C / ctx.lambda0
        # Radiation resistance
        if Cn < 0.1:
            mode = "small loop"
            Rr = 20 * np.pi ** 2 * Cn ** 4
            L_self = 4 * np.pi * a * 2e-7 * (np.log(8 * a / aw) - 2)
            X_L = 2 * np.pi * ctx.fr * L_self
        else:
            mode = "resonant / large loop"
            Rr = 100.0  # approximate for 1λ loop
            X_L = 0.0
        return {"a": a, "aw": aw, "C": C, "C_over_lambda": Cn,
                "mode": mode, "Rr": Rr, "X_L": X_L}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Loop radius       = {r['a']*m:.3f} {u}",
            f"  Wire radius       = {r['aw']*m:.3f} {u}",
            f"  Circumference     = {r['C']*m:.3f} {u}  ({r['C_over_lambda']:.3f} λ)",
            f"  Mode              = {r['mode']}",
            f"  R_radiation       = {r['Rr']:.3g} Ω",
            f"  X_L (small loop)  = {r['X_L']:.1f} Ω",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        a = r["a"] * m
        aw = max(r["aw"] * m, a * 0.006)  # draw at least visibly
        style_ax(ax.figure, ax, "Circular Loop (top view)", equal=True)

        # Wire as annulus — outer radius a+aw, inner a-aw, with a small feed gap
        gap_deg = 6.0
        th = np.linspace(np.radians(gap_deg/2),
                         2*np.pi - np.radians(gap_deg/2), 400)
        x_out = (a + aw) * np.cos(th)
        y_out = (a + aw) * np.sin(th)
        x_in  = (a - aw) * np.cos(th[::-1])
        y_in  = (a - aw) * np.sin(th[::-1])
        pts = np.column_stack([np.r_[x_out, x_in], np.r_[y_out, y_in]])
        ax.add_patch(mpatches.Polygon(pts,
                     facecolor=LAYER_COLORS["wire"],
                     edgecolor=LAYER_COLORS["wire_edge"] if "wire_edge" in LAYER_COLORS
                               else LAYER_COLORS["text"],
                     lw=0.5, zorder=3))

        # Feed terminals (two little pads at the gap)
        g_ang = np.radians(gap_deg / 2)
        px1, py1 = a * np.cos(+g_ang), a * np.sin(+g_ang)
        px2, py2 = a * np.cos(-g_ang), a * np.sin(-g_ang)
        ax.plot([px1, px2], [py1, py2], "o", color="red",
                markersize=5, zorder=5)
        # Short coax-style leader to SMA marker below the gap
        sma_x, sma_y = a + 2.5 * aw + 0.08 * a, 0.0
        ax.plot([a, sma_x], [0, 0], color=LAYER_COLORS["feed"]
                if "feed" in LAYER_COLORS else "#00c8ff",
                lw=1.2, ls=(0, (4, 2)), zorder=4)
        ax.add_patch(mpatches.Circle((sma_x, sma_y), aw * 2.5, fill=False,
                     edgecolor=LAYER_COLORS["feed"] if "feed" in LAYER_COLORS
                               else "#00c8ff", lw=1.0, ls=":", zorder=4))
        ax.text(sma_x, sma_y - aw * 3.5, "SMA",
                ha="center", va="top", fontsize=8,
                color=LAYER_COLORS["feed"] if "feed" in LAYER_COLORS else "#00c8ff")

        # Dimensions
        dim_radial(ax, (0, 0), a, 45, f"r = {a:.3f}")
        ax.text(0, -a * 1.25, f"2r = {2*a:.3f}   wire Ø = {2*aw:.3f}",
                ha="center", va="top", fontsize=8,
                color=LAYER_COLORS["text"])
        ax.margins(0.3)

    def plot_fields(self, ax, ctx, r):
        ax.text(0.5, 0.5, f"{r['mode']}: current ~ constant around loop",
                ha="center", va="center", transform=ax.transAxes,
                color=LAYER_COLORS["text"], fontsize=11)
        ax.set_axis_off()

    def pattern(self, theta, phi, ctx, r):
        # Small loop: |F| = sin θ (like magnetic dipole along z)
        # Large loop: more complex, but for 1λ we get main lobe in the plane of the loop
        Cn = r["C_over_lambda"]
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        if Cn < 0.2:
            return np.abs(np.sin(theta_b))
        else:
            # Resonant loop: J1(kа·sinθ) / (kа·sinθ)  (approx)
            from scipy.special import jv
            x = 2 * np.pi * Cn / 2 * np.sin(theta_b)   # ka·sinθ
            with np.errstate(divide="ignore", invalid="ignore"):
                F = np.where(np.abs(x) < 1e-9, 1.0, jv(1, x) / x * 2)
            return np.abs(F)
