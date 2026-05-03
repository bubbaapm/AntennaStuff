"""
Linear phased array (generic) — N isotropic elements, user-defined spacing
and progressive phase β.
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches

from .base import AntennaBase, Context, Input, register_antenna, C_LIGHT
from plotting.cad import LAYER_COLORS, style_ax, dim_horizontal, leader


@register_antenna("Linear Phased Array", category="Array")
class LinearPhasedArray(AntennaBase):
    notes = ("N isotropic elements along x, spacing d (in λ). "
             "AF(θ,φ) = sin(Nψ/2)/(N·sin(ψ/2)) with ψ = k·d·sinθ·cosφ + β.")

    def inputs(self):
        return [
            Input("N",         "Number of elements N",    "8"),
            Input("d_lambda",  "Spacing d (λ)",           "0.5"),
            Input("beta_deg",  "Progressive phase β (°)", "0"),
            Input("taper",     "Amplitude taper (uniform/chebyshev/hamming)",
                                                         "uniform"),
        ]

    def compute(self, ctx, params):
        N = int(float(params.get("N", "8")))
        d_lam = float(params.get("d_lambda", "0.5"))
        beta = np.radians(float(params.get("beta_deg", "0")))
        taper = params.get("taper", "uniform").strip().lower()

        d = d_lam * ctx.lambda0
        # Amplitude weights
        n = np.arange(N)
        if taper == "uniform":
            w = np.ones(N)
        elif taper.startswith("ham"):
            w = 0.54 - 0.46 * np.cos(2 * np.pi * n / (N - 1))
        elif taper.startswith("cheb"):
            # simple cosine window as a placeholder
            w = 0.5 - 0.5 * np.cos(2 * np.pi * n / (N - 1))
        else:
            w = np.ones(N)
        w = w / np.max(w)

        # Steering direction from β
        if d > 0:
            cos_main = -beta / (2 * np.pi * d_lam)
            if np.abs(cos_main) <= 1:
                steer_deg = np.degrees(np.arccos(cos_main))
            else:
                steer_deg = np.nan
        else:
            steer_deg = np.nan
        # Array length
        L_arr = (N - 1) * d
        return {"N": N, "d": d, "d_lambda": d_lam, "beta_rad": beta,
                "beta_deg": float(params.get("beta_deg", "0")),
                "weights": w, "taper": taper,
                "steer_deg": steer_deg, "L_arr": L_arr}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        out = [
            f"  N                = {r['N']}",
            f"  d                = {r['d']*m:.3f} {u}  ({r['d_lambda']:.3f} λ)",
            f"  β (progressive)  = {r['beta_deg']:.2f}°",
            f"  Taper            = {r['taper']}",
            f"  Array length     = {r['L_arr']*m:.3f} {u}",
        ]
        if np.isfinite(r['steer_deg']):
            out.append(f"  Steered beam at  = {r['steer_deg']:.2f}° (from broadside along +x)")
        return out

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        d = r["d"] * m
        N = r["N"]
        style_ax(ax.figure, ax, f"Linear Array: N={N}, d={r['d_lambda']:.2f}λ",
                 equal=True)
        weights = r["weights"]
        positions = (np.arange(N) - (N - 1) / 2) * d
        for x, w in zip(positions, weights):
            size = 0.3 * d * (0.5 + 0.5 * w)
            ax.add_patch(mpatches.Circle((x, 0), size,
                                         facecolor=LAYER_COLORS["copper"],
                                         edgecolor=LAYER_COLORS["axis"], zorder=2))
            ax.text(x, -0.9 * d, f"{w:.2f}", ha="center", va="top",
                    fontsize=8, color=LAYER_COLORS["text"])
        ax.plot(positions, np.zeros_like(positions), color="white", lw=0.8, zorder=1)
        dim_horizontal(ax, positions[0], positions[-1], d*1.4,
                       f"L = {(N-1)*d:.2f}", offset=0)
        if N > 1:
            dim_horizontal(ax, positions[0], positions[1], d*0.6,
                           f"d = {d:.2f}", offset=0, color=LAYER_COLORS["dim_alt"])
        ax.set_ylim(-2 * d, 2.2 * d)

    def plot_fields(self, ax, ctx, r):
        # Show AF vs angle plus β-sweep overlay
        ax.set_title("Array Factor — β sweep", color=LAYER_COLORS["text"])
        style_ax(ax.figure, ax, "Array Factor Magnitude vs θ (broadside @ 90°)",
                 equal=False, grid=True)
        N = r["N"]
        d_lam = r["d_lambda"]
        theta = np.linspace(0, np.pi, 720)
        kd = 2 * np.pi * d_lam
        for b_deg, color in zip([-90, -45, 0, 45, 90],
                                ["#ff7ab6", "#ffd34d", "#00e0b4", "#4ac0ff", "#c07aff"]):
            b = np.radians(b_deg)
            psi = kd * np.cos(theta) + b
            with np.errstate(divide="ignore", invalid="ignore"):
                AF = np.abs(np.sin(N*psi/2) / (N * np.sin(psi/2)))
            AF[np.isnan(AF)] = 1
            ax.plot(np.degrees(theta), AF, lw=1.3, color=color, label=f"β={b_deg}°")
        ax.axvline(90, color="#555", ls="--", lw=0.7)
        ax.set_xlabel("θ (°)", color=LAYER_COLORS["text"])
        ax.set_ylabel("|AF|", color=LAYER_COLORS["text"])
        ax.legend(loc="upper right", facecolor=LAYER_COLORS["panel_bg"],
                  edgecolor=LAYER_COLORS["axis"],
                  labelcolor=LAYER_COLORS["text"], fontsize=8)

    def pattern(self, theta, phi, ctx, r):
        N = r["N"]
        d = r["d"]
        beta = r["beta_rad"]
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        phi_b = np.broadcast_to(phi, np.broadcast_shapes(theta.shape, phi.shape))
        psi = k0 * d * np.sin(theta_b) * np.cos(phi_b) + beta
        with np.errstate(divide="ignore", invalid="ignore"):
            AF = np.sin(N * psi / 2) / (N * np.sin(psi / 2))
        AF = np.where(np.isnan(AF), 1.0, AF)
        return np.abs(AF)
