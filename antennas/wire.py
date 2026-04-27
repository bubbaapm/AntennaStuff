"""
Wire-type antennas — dipole, monopole, Yagi-Uda, LPDA.

Wire radius affects the resonant shortening factor. We use a small polynomial
approximation based on King-Middleton / Hallén-type results:

    k_short ≈ 0.5 − 0.025 · log10( L/d )   (dipole)

giving k ≈ 0.475 at L/d = 100 and k ≈ 0.495 for extremely thin wire.
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches

from .base import AntennaBase, Context, Input, register_antenna, C_LIGHT
from plotting.cad import (
    LAYER_COLORS, style_ax, dim_horizontal, dim_vertical, leader,
    add_layer_legend,
)


def _dipole_shortening(length_to_diameter: float) -> float:
    """Return resonant length in units of λ."""
    Ld = max(length_to_diameter, 5.0)
    return 0.5 - 0.025 * np.log10(Ld)


# ============================================================================
# Half-wave Dipole
# ============================================================================

@register_antenna("Half-Wave Dipole", category="Wire")
class HalfWaveDipole(AntennaBase):
    notes = "Resonant length shortened by end-effect; depends on L/d ratio."

    def inputs(self):
        return [
            Input("wire_r", "Wire radius (units)", "0.5"),
            Input("gap",    "Feed gap (units)",    "1.0"),
        ]

    def compute(self, ctx, params):
        a = float(params.get("wire_r", "0.5")) * 1e-3
        gap = float(params.get("gap", "1.0")) * 1e-3
        # iterative: initial guess L = 0.475λ
        L = 0.475 * ctx.lambda0
        for _ in range(5):
            Ld = L / (2 * a)
            L = _dipole_shortening(Ld) * ctx.lambda0
        # Feedpoint impedance at resonance (thin-wire ≈ 73 + j0 Ω ideally, shifts with L/d)
        # Use approximation: R_in ≈ 73 · (1 - 0.05·log10(L/d))
        Ld = L / (2 * a)
        R_in = 73.1 * (1 - 0.05 * np.log10(max(Ld, 5.0))) if Ld > 5 else 73.1
        return {"L": L, "a": a, "gap": gap, "R_in": R_in, "L_over_d": Ld}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Total length L = {r['L']*m:.4f} {u}  (≈ {r['L']/ctx.lambda0:.4f} λ)",
            f"  Wire radius a  = {r['a']*m:.4f} {u}",
            f"  L/d ratio      = {r['L_over_d']:.1f}",
            f"  Feed gap       = {r['gap']*m:.4f} {u}",
            f"  R_in (resonant)= {r['R_in']:.1f} Ω",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, a, gap = r["L"] * m, r["a"] * m, r["gap"] * m
        style_ax(ax.figure, ax, "Half-Wave Dipole", equal=True)
        # each arm
        ax.add_patch(mpatches.Rectangle((-L/2, -a), (L-gap)/2, 2*a,
                                         facecolor=LAYER_COLORS["wire"],
                                         edgecolor=LAYER_COLORS["axis"], zorder=2))
        ax.add_patch(mpatches.Rectangle((gap/2, -a), (L-gap)/2, 2*a,
                                         facecolor=LAYER_COLORS["wire"],
                                         edgecolor=LAYER_COLORS["axis"], zorder=2))
        # feedpoint
        ax.plot([0], [0], "o", color="red", markersize=6, zorder=5,
                label="Feedpoint")
        dim_horizontal(ax, -L/2, L/2, a * 8, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -a, a, L/2 + L*0.05,
                     f"Ø{2*a:.2f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        dim_horizontal(ax, -gap/2, gap/2, -a*10, f"gap = {gap:.2f}",
                       offset=0, color=LAYER_COLORS["dim_alt"])
        ax.set_ylim(-L*0.15, L*0.15)
        ax.legend(loc="lower right", facecolor=LAYER_COLORS["panel_bg"],
                  edgecolor=LAYER_COLORS["axis"], labelcolor=LAYER_COLORS["text"])

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "Dipole Current Distribution |I(z)|",
                 equal=False, grid=True)
        L = r["L"] * ctx.out_mult
        z = np.linspace(-L/2, L/2, 400)
        I = np.abs(np.cos(np.pi * z / L))
        ax.plot(z, I, color="#00FFCC", lw=2)
        ax.fill_between(z, 0, I, color="#00FFCC", alpha=0.25)
        ax.set_xlabel(f"z ({ctx.unit_str})", color=LAYER_COLORS["text"])
        ax.set_ylabel("|I(z)| normalized", color=LAYER_COLORS["text"])
        ax.set_ylim(0, 1.05)

    def pattern(self, theta, phi, ctx, r):
        # Oriented along z; pattern is |cos(kL/2·cosθ) − cos(kL/2)| / sin θ
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        kL = k0 * r["L"]
        # broadcast to (theta+phi) shape
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        with np.errstate(divide="ignore", invalid="ignore"):
            num = np.cos(kL/2 * np.cos(theta_b)) - np.cos(kL/2)
            den = np.sin(theta_b)
            F = np.where(np.abs(den) < 1e-9, 0.0, np.abs(num) / np.abs(den))
        return F


# ============================================================================
# Quarter-wave Monopole
# ============================================================================

@register_antenna("Quarter-Wave Monopole", category="Wire")
class QuarterMonopole(AntennaBase):
    notes = "Vertical over ground plane. Same pattern as dipole in upper hemisphere, ~half R_in."

    def inputs(self):
        return [
            Input("wire_r", "Wire radius (units)", "0.5"),
            Input("gnd_radius", "Ground plane radius (units)", "25.0"),
        ]

    def compute(self, ctx, params):
        a = float(params.get("wire_r", "0.5")) * 1e-3
        gnd = float(params.get("gnd_radius", "25.0")) * 1e-3
        L = 0.25 * ctx.lambda0
        for _ in range(5):
            Ld = 2 * L / (2 * a)
            L = 0.5 * _dipole_shortening(Ld) * ctx.lambda0
        R_in = 36.5
        return {"L": L, "a": a, "gnd": gnd, "R_in": R_in}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Vertical length L = {r['L']*m:.4f} {u}",
            f"  Wire radius       = {r['a']*m:.4f} {u}",
            f"  Ground plane r    = {r['gnd']*m:.4f} {u}",
            f"  R_in ≈            = {r['R_in']:.1f} Ω",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, a, gnd = r["L"] * m, r["a"] * m, r["gnd"] * m
        style_ax(ax.figure, ax, "Quarter-Wave Monopole", equal=True)
        # Ground
        ax.add_patch(mpatches.Rectangle((-gnd, -0.02*L), 2*gnd, 0.02*L,
                                         facecolor="#3c3c3c",
                                         edgecolor=LAYER_COLORS["axis"], zorder=1))
        # Wire
        ax.add_patch(mpatches.Rectangle((-a, 0), 2*a, L,
                                         facecolor=LAYER_COLORS["wire"],
                                         edgecolor=LAYER_COLORS["axis"], zorder=2))
        ax.plot([0], [0], "o", color="red", markersize=6, zorder=5)
        dim_vertical(ax, 0, L, a*8, f"L = {L:.2f}", offset=0)
        dim_horizontal(ax, -gnd, gnd, -0.04*L, f"GND Ø = {2*gnd:.2f}", offset=0,
                       color=LAYER_COLORS["dim_alt"])

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "Monopole Current Distribution |I(z)|",
                 equal=False, grid=True)
        L = r["L"] * ctx.out_mult
        z = np.linspace(0, L, 200)
        I = np.abs(np.sin(np.pi * (L - z) / (2 * L)))
        ax.plot(z, I, color="#00FFCC", lw=2)
        ax.fill_between(z, 0, I, color="#00FFCC", alpha=0.25)
        ax.set_xlabel(f"z ({ctx.unit_str})")
        ax.set_ylabel("|I(z)| normalized")
        ax.set_ylim(0, 1.05)

    def pattern(self, theta, phi, ctx, r):
        # Upper hemisphere only (θ ∈ [0, π/2])
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        kL = k0 * r["L"]
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        with np.errstate(divide="ignore", invalid="ignore"):
            num = np.cos(kL * np.cos(theta_b)) - np.cos(kL)
            den = np.sin(theta_b)
            F = np.where(np.abs(den) < 1e-9, 0.0, np.abs(num) / np.abs(den))
        F = np.where(np.cos(theta_b) > 0, F, 0)
        return F


# ============================================================================
# Yagi-Uda (N-element)
# ============================================================================

@register_antenna("Yagi-Uda", category="Wire")
class YagiUda(AntennaBase):
    notes = "NBS / Viezbicke-style dimensions — 1 reflector, 1 driven, N-2 directors."

    def inputs(self):
        return [
            Input("n_elements", "Total elements (≥3)", "5"),
            Input("wire_r", "Wire radius (units)", "1.0"),
        ]

    # NBS Table for d/λ = 0.0085, boom d/λ = 0.0085.
    # Values from Balanis Appendix, Yagi element lengths (λ).
    _NBS = {
        # N: (reflector, driven, director lengths..., spacing)
        3:  {"LR": 0.482, "LD": 0.475, "LDIRS": [0.440],
             "SR": 0.20, "SD": 0.20},
        4:  {"LR": 0.482, "LD": 0.459, "LDIRS": [0.424, 0.424],
             "SR": 0.20, "SD": 0.25},
        5:  {"LR": 0.482, "LD": 0.457, "LDIRS": [0.442, 0.424, 0.424],
             "SR": 0.20, "SD": 0.31},
        6:  {"LR": 0.475, "LD": 0.455, "LDIRS": [0.432, 0.415, 0.407, 0.398],
             "SR": 0.20, "SD": 0.31},
        7:  {"LR": 0.484, "LD": 0.459, "LDIRS": [0.443, 0.430, 0.418, 0.409, 0.404],
             "SR": 0.20, "SD": 0.31},
    }

    def compute(self, ctx, params):
        N = max(3, int(float(params.get("n_elements", "5"))))
        N = min(N, 7)
        a = float(params.get("wire_r", "1.0")) * 1e-3
        t = self._NBS[N]
        lam = ctx.lambda0
        L_refl = t["LR"] * lam
        L_drvn = t["LD"] * lam
        L_dirs = [ld * lam for ld in t["LDIRS"]]
        S_refl = t["SR"] * lam
        S_dirs = [t["SD"] * lam] * (N - 2)  # driven → first director → subsequent
        boom_len = S_refl + sum(S_dirs)
        # Simple gain estimate (Balanis figure-of-merit): Gain ≈ 8·log(N) + 2 dBi
        gain_est = 6 + 2.5 * np.log10(N)
        return {
            "N": N, "a": a,
            "L_refl": L_refl, "L_drvn": L_drvn, "L_dirs": L_dirs,
            "S_refl": S_refl, "S_dirs": S_dirs, "boom": boom_len,
            "gain_dBi_est": gain_est,
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        out = [
            f"  Elements (N)      = {r['N']}",
            f"  Reflector L       = {r['L_refl']*m:.3f} {u}",
            f"  Driven L          = {r['L_drvn']*m:.3f} {u}",
        ]
        for i, ld in enumerate(r['L_dirs']):
            out.append(f"  Director {i+1} L    = {ld*m:.3f} {u}")
        out.append(f"  Reflector spacing = {r['S_refl']*m:.3f} {u}")
        for i, sd in enumerate(r['S_dirs']):
            out.append(f"  Spacing to dir {i+1} = {sd*m:.3f} {u}")
        out.append(f"  Total boom        = {r['boom']*m:.3f} {u}")
        out.append(f"  Estimated gain    = {r['gain_dBi_est']:.1f} dBi")
        return out

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        a = r["a"] * m
        # Positions along x
        positions = [-r["S_refl"] * m, 0.0]
        lengths = [r["L_refl"] * m, r["L_drvn"] * m]
        colors = ["silver", LAYER_COLORS["copper"]]
        labels = ["Reflector", "Driven"]
        x = 0.0
        for i, (sd, ld) in enumerate(zip(r["S_dirs"], r["L_dirs"])):
            x += sd * m
            positions.append(x)
            lengths.append(ld * m)
            colors.append("silver")
            labels.append(f"Director {i+1}")
        style_ax(ax.figure, ax, f"Yagi-Uda ({r['N']} elements)", equal=True)
        # Boom
        boom_len = positions[-1] - positions[0]
        ax.plot([positions[0], positions[-1]], [0, 0], "w-", lw=1.5, zorder=1)
        # Elements
        for x, L, c, lbl in zip(positions, lengths, colors, labels):
            ax.add_patch(mpatches.Rectangle((x - a, -L/2), 2*a, L,
                                             facecolor=c,
                                             edgecolor=LAYER_COLORS["axis"], zorder=2))
            ax.text(x, L/2 + r["L_refl"]*m*0.06, lbl, ha="center",
                    color=LAYER_COLORS["text"], fontsize=8, zorder=3)
        # Dimensions
        max_L = max(lengths)
        dim_horizontal(ax, positions[0], positions[-1], -max_L/2 - max_L*0.15,
                       f"Boom = {boom_len:.1f}", offset=0)
        for i, (p, L) in enumerate(zip(positions[1:], lengths[1:]), start=1):
            dim_vertical(ax, -L/2, L/2, p + max_L*0.03 + a*3,
                         f"{L:.1f}", offset=0, color=LAYER_COLORS["dim_alt"])
        dim_vertical(ax, -lengths[0]/2, lengths[0]/2,
                     positions[0] - max_L*0.06,
                     f"{lengths[0]:.1f}", offset=0, color=LAYER_COLORS["dim_alt"])

    def plot_fields(self, ax, ctx, r):
        ax.text(0.5, 0.5, "Yagi: see 3D / 2D Pattern tabs",
                ha="center", va="center", transform=ax.transAxes,
                color=LAYER_COLORS["text"], fontsize=12)
        ax.set_axis_off()

    def pattern(self, theta, phi, ctx, r):
        # Crude end-fire approximation: F(θ,φ) = |cos(θ_x)|^N where θ_x is angle from +x
        # This is a stand-in; real Yagi pattern requires mutual-impedance solution.
        # Use: main beam along +x.
        # Angle from +x axis:
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        phi_b = np.broadcast_to(phi, np.broadcast_shapes(theta.shape, phi.shape))
        cos_ax = np.sin(theta_b) * np.cos(phi_b)
        N = r["N"]
        # Beam sharpness scales with N
        sharpness = 2 + 0.8 * (N - 3)
        cos_pos = np.clip(cos_ax, 0.0, None)
        F = cos_pos ** sharpness
        # Add a small back lobe ~ -15 dB
        cos_neg = np.clip(-cos_ax, 0.0, None)
        back = 0.18 * cos_neg ** 2
        return F + back


# ============================================================================
# LPDA (Log-Periodic Dipole Array)
# ============================================================================

@register_antenna("Log-Periodic Dipole Array (LPDA)", category="Wire")
class LPDA(AntennaBase):
    notes = ("Carrel's design. τ=length ratio (0.8–0.95), σ=relative spacing (0.12–0.22). "
             "Higher τ and σ → more gain, longer boom.")

    def inputs(self):
        return [
            Input("f_low_GHz",  "Low frequency (GHz)",  "1.0"),
            Input("f_high_GHz", "High frequency (GHz)", "3.0"),
            Input("tau",        "Scaling ratio τ",       "0.88"),
            Input("sigma",      "Relative spacing σ",    "0.17"),
            Input("wire_r",     "Wire radius (units)",   "1.0"),
        ]

    def compute(self, ctx, params):
        fL = float(params.get("f_low_GHz", "1")) * 1e9
        fH = float(params.get("f_high_GHz", "3")) * 1e9
        tau = float(params.get("tau", "0.88"))
        sigma = float(params.get("sigma", "0.17"))
        a = float(params.get("wire_r", "1.0")) * 1e-3

        # Longest dipole ≈ λ/2 at fL; boundary factor b=1.1 to cover fL cleanly
        bar = 1.1
        L1 = 0.5 * C_LIGHT / fL * bar
        # Number of elements: L_N = λ/2 at fH, with L_n = τ^(n-1) · L_1
        # Solve τ^(N-1) = (λ_H/2) / L_1 ⇒ N = 1 + log(.)/log(τ)
        LN_min = 0.5 * C_LIGHT / fH
        N = int(np.ceil(1 + np.log(LN_min / L1) / np.log(tau)))
        N = max(N, 5)
        # Build lengths and spacings
        lengths = [L1 * tau ** (n) for n in range(N)]
        spacings = [2 * sigma * lengths[n] for n in range(N - 1)]  # d_n = 2σ·L_n
        boom = sum(spacings)
        # Approx gain (Carrel): G_dBi ≈ 7 + 45·(σ - 0.05)  roughly
        # More standard: use a fit — G ≈ 7 + 35·σ·τ
        gain = 7 + 35 * sigma * tau
        return {
            "N": N, "a": a, "tau": tau, "sigma": sigma,
            "lengths": lengths, "spacings": spacings, "boom": boom,
            "f_low": fL, "f_high": fH, "gain_dBi_est": gain,
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        out = [
            f"  Elements N       = {r['N']}",
            f"  τ = {r['tau']}, σ = {r['sigma']}",
            f"  Longest dipole   = {r['lengths'][0]*m:.2f} {u}",
            f"  Shortest dipole  = {r['lengths'][-1]*m:.2f} {u}",
            f"  Boom length      = {r['boom']*m:.2f} {u}",
            f"  Estimated gain   = {r['gain_dBi_est']:.1f} dBi",
            f"  Band             = {r['f_low']/1e9:.2f} – {r['f_high']/1e9:.2f} GHz",
        ]
        return out

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        a = r["a"] * m
        style_ax(ax.figure, ax, f"LPDA ({r['N']} dipoles)", equal=True)
        # Two booms with alternating polarity — draw a single boom line for simplicity
        x = 0
        max_L = r["lengths"][0] * m
        for i, L in enumerate(r["lengths"]):
            Lm = L * m
            polarity = 1 if i % 2 == 0 else -1
            # Upper and lower arms from a central boom
            ax.add_patch(mpatches.Rectangle((x - a, 0.01*max_L),
                                             2*a, polarity * Lm/2,
                                             facecolor=LAYER_COLORS["wire"], zorder=2))
            ax.add_patch(mpatches.Rectangle((x - a, -0.01*max_L),
                                             2*a, -polarity * Lm/2,
                                             facecolor=LAYER_COLORS["wire"], zorder=2))
            if i < len(r["spacings"]):
                x += r["spacings"][i] * m
        ax.plot([0, x], [0, 0], color="white", lw=1)
        ax.plot([0, x], [-0.008*max_L, -0.008*max_L], color="white", lw=1)
        dim_horizontal(ax, 0, x, -max_L * 0.6, f"Boom = {x:.1f}", offset=0)
        dim_vertical(ax, -r["lengths"][0]*m/2, r["lengths"][0]*m/2,
                     -max_L*0.05, f"L₁ = {r['lengths'][0]*m:.1f}",
                     offset=0, color=LAYER_COLORS["dim_alt"])
        dim_vertical(ax, -r["lengths"][-1]*m/2, r["lengths"][-1]*m/2,
                     x + max_L*0.05, f"L_N = {r['lengths'][-1]*m:.1f}",
                     offset=0, color=LAYER_COLORS["dim_alt"])

    def plot_fields(self, ax, ctx, r):
        ax.text(0.5, 0.5, "LPDA: see 3D / 2D Pattern tabs",
                ha="center", va="center", transform=ax.transAxes,
                color=LAYER_COLORS["text"], fontsize=12)
        ax.set_axis_off()

    def pattern(self, theta, phi, ctx, r):
        # Broadband end-fire beam; simple approximation similar to Yagi
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        phi_b = np.broadcast_to(phi, np.broadcast_shapes(theta.shape, phi.shape))
        cos_ax = np.sin(theta_b) * np.cos(phi_b)
        sharp = 2 + 1.5 * r["tau"]
        return np.clip(cos_ax, 0.0, None) ** sharp
