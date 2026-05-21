"""
Planar spiral antennas — Archimedean and equiangular (log-periodic) spirals.

Two arms wound in opposite phases (180° offset). Once a turn fits the
half-wavelength resonance condition the corresponding annular ring radiates
broadside with circular polarization — the operating band runs from where
the OUTERMOST ring satisfies r ≈ λ/(2π) down to where the INNERMOST ring
does. Bandwidth is set by the radius ratio.
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches
from matplotlib.path import Path as MPath

from .base import AntennaBase, Context, Input, Curve, register_antenna, C_LIGHT, ETA0
from plotting.cad import (
    LAYER_COLORS, style_ax, dim_radial, dim_diameter, leader,
    add_layer_legend, dim_board,
)


# ============================================================================
# Archimedean spiral
# ============================================================================

@register_antenna("Archimedean Spiral (Planar)", category="Aperture")
class ArchimedeanSpiral(AntennaBase):
    notes = (
        "Two-arm planar spiral, arms offset 180°. The active region is the "
        "annulus where the circumference ≈ λ, so the band runs from "
        "f_low ≈ c/(2π·r_outer) up to f_high ≈ c/(2π·r_inner). "
        "Self-complementary geometry → Z₀ ≈ 188 Ω, typical 1:1 → 188 Ω balun. "
        "Broadside circular polarization (RHCP if you wind counter-clockwise "
        "looking at the +Z face)."
    )
    polarization = "circular  (RHCP from +Z if wound CCW)"
    beam_axis = "broadside (+Z), bidirectional unless backed by a cavity"
    bandwidth_note = "very wideband — set by r_outer / r_inner ratio"

    def inputs(self):
        return [
            Input("n_turns",   "Turns per arm",           "4"),
            Input("r_outer",   "Outer radius r₂",         "30.0", unit="units",
                  tooltip="Sets the LOW-frequency edge: f_low ≈ c/(2π·r₂)."),
            Input("r_inner",   "Inner / feed radius r₁",  "1.0", unit="units",
                  tooltip="Sets the HIGH-frequency edge: f_high ≈ c/(2π·r₁)."),
            Input("arm_width", "Strip width",             "1.5", unit="units"),
            Input("margin",    "Board margin past spiral", "5.0", unit="units"),
        ]

    def compute(self, ctx: Context, params: dict) -> dict:
        N_turns = max(1, int(float(params.get("n_turns", "4"))))
        r2 = ctx.m(params.get("r_outer", "30.0"))
        r1 = ctx.m(params.get("r_inner", "1.0"))
        if r1 >= r2:
            r1 = r2 * 0.05
        a_strip = ctx.m(params.get("arm_width", "1.5"))
        margin  = ctx.m(params.get("margin", "5.0"))

        # Archimedean spacing constant (per radian): r(θ) = r1 + (Δr / (2π·N))·θ
        a = (r2 - r1) / (2 * np.pi * N_turns)

        # Operating band — active region condition r = λ/(2π)
        fL = C_LIGHT / (2 * np.pi * r2)
        fH = C_LIGHT / (2 * np.pi * r1)

        # Self-complementary impedance (Babinet)
        Z_self = ETA0 / 2.0   # ≈ 188.4 Ω

        # Gain estimate (single-sided, with cavity backing typical ≈ 6 dBi)
        gain_est = 5.0

        # --- Build parametric points -----------------------------------
        # Two arms, second offset by 180°. Sample at 24 points per turn.
        pts_per_turn = 24
        t = np.linspace(0.0, 2 * np.pi * N_turns, N_turns * pts_per_turn + 1)
        r_t = r1 + a * t
        arm1 = list(zip(r_t * np.cos(t), r_t * np.sin(t)))
        arm2 = list(zip(r_t * np.cos(t + np.pi), r_t * np.sin(t + np.pi)))

        mu = ctx.out_mult
        r1_d = r1 * mu
        a_d  = a  * mu       # display-unit per radian
        curves = [
            Curve(
                name="Spiral arm 1 (centreline)",
                equation="r(θ) = r₁ + a·θ;   x = r·cos θ, y = r·sin θ",
                parameters={"r1": (r1, "m"),
                            "r2": (r2, "m"),
                            "a":  (a,  "m/rad"),
                            "N":  (N_turns, " turns"),
                            "θ":  ((0.0, 2*np.pi*N_turns), "rad")},
                points_m=[(float(x), float(y)) for x, y in arm1],
                note=("Strip width 2·a_strip drawn perpendicular to this path."),
                cst={
                    "x_t": f"({r1_d:.6f} + {a_d:.6f}*t)*cos(t)",
                    "y_t": f"({r1_d:.6f} + {a_d:.6f}*t)*sin(t)",
                    "z_t": "0",
                    "t_min": "0",
                    "t_max": f"2*pi*{N_turns}",
                    "t_unit": "rad",
                },
            ),
            Curve(
                name="Spiral arm 2 (centreline, 180° offset)",
                equation="r(θ) = r₁ + a·θ;   x = r·cos(θ+π), y = r·sin(θ+π)",
                parameters={"r1": (r1, "m"),
                            "a":  (a,  "m/rad")},
                points_m=[(float(x), float(y)) for x, y in arm2],
                cst={
                    "x_t": f"({r1_d:.6f} + {a_d:.6f}*t)*cos(t+pi)",
                    "y_t": f"({r1_d:.6f} + {a_d:.6f}*t)*sin(t+pi)",
                    "z_t": "0",
                    "t_min": "0",
                    "t_max": f"2*pi*{N_turns}",
                    "t_unit": "rad",
                },
            ),
        ]

        bw = {"f_low_hz": fL, "f_high_hz": fH,
              "fractional": 2*(fH-fL)/(fH+fL),
              "note": "Active-region rule: r·(2π) ≈ λ at the operating freq."}

        outer = 2 * (r2 + margin)
        return {
            "N_turns": N_turns, "r1": r1, "r2": r2,
            "a": a, "arm_w": a_strip, "margin": margin,
            "f_low": fL, "f_high": fH,
            "Z_self": Z_self, "Gain_dBi": gain_est,
            "board_size": (outer, outer),
            "curves": curves,
            "bandwidth": bw,
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Turns           = {r['N_turns']}",
            f"  Inner radius r₁ = {r['r1']*m:.3f} {u}",
            f"  Outer radius r₂ = {r['r2']*m:.3f} {u}",
            f"  Spacing a       = {r['a']*m:.4f} {u} / rad",
            f"  Strip width     = {r['arm_w']*m:.3f} {u}",
            "",
            f"  Active band     = {r['f_low']/1e9:.2f} – {r['f_high']/1e9:.2f} GHz",
            f"  Z_self (Babinet)= {r['Z_self']:.1f} Ω   "
            f"(use ≈4:1 balun for 50 Ω feed)",
            f"  Estimated gain  ≈ {r['Gain_dBi']:.1f} dBi   "
            f"(planar, no cavity)",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        r1, r2 = r["r1"] * m, r["r2"] * m
        a_strip = r["arm_w"] * m
        margin = r["margin"] * m
        N = r["N_turns"]

        style_ax(ax.figure, ax, f"Archimedean Spiral — {N} turns", equal=True)
        # Substrate
        board_r = r2 + margin
        ax.add_patch(mpatches.Rectangle(
            (-board_r, -board_r), 2 * board_r, 2 * board_r,
            facecolor=LAYER_COLORS["substrate"],
            edgecolor=LAYER_COLORS["axis"], lw=0.7, zorder=1))

        # Draw both spiral arms as filled "ribbons" using the centreline ± half-width
        pts_per_turn = 200
        t = np.linspace(0.0, 2 * np.pi * N, max(pts_per_turn * N, 200))
        a_per_rad = (r2 - r1) / (2 * np.pi * N)
        r_t = (r1 + a_per_rad * t)
        # Normal direction at each point (tangent normal)
        # In planar coords with r = r1 + a*θ:
        #   dx/dθ = a·cosθ − r·sinθ
        #   dy/dθ = a·sinθ + r·cosθ
        # Normal = (dy, −dx)/|·|  -> perpendicular to tangent
        dx = a_per_rad * np.cos(t) - r_t * np.sin(t)
        dy = a_per_rad * np.sin(t) + r_t * np.cos(t)
        norm = np.hypot(dx, dy)
        nx = dy / norm
        ny = -dx / norm

        for phase_offset, color, edge in (
            (0.0, LAYER_COLORS["copper"], LAYER_COLORS["copper_edge"]),
            (np.pi, "#cc7733", "#a55a1a"),
        ):
            cs = np.cos(t + phase_offset); sn = np.sin(t + phase_offset)
            cx = r_t * cs
            cy = r_t * sn
            x_outer = cx + a_strip/2 * nx
            y_outer = cy + a_strip/2 * ny
            x_inner = cx - a_strip/2 * nx
            y_inner = cy - a_strip/2 * ny
            poly = list(zip(x_outer, y_outer)) + list(zip(x_inner[::-1], y_inner[::-1]))
            ax.add_patch(mpatches.Polygon(poly, closed=True,
                                          facecolor=color, edgecolor=edge,
                                          lw=0.6, zorder=3))

        # Feed at centre
        ax.plot([0], [0], "o", color="red", markersize=5, zorder=6)

        # Dimensions
        dim_radial(ax, (0, 0), r2, 30, f"r₂ = {r2:.2f}")
        dim_radial(ax, (0, 0), r1, 150, f"r₁ = {r1:.3f}",
                   color=LAYER_COLORS["dim_alt"])
        leader(ax, (r1 * np.cos(np.radians(-60)),
                    r1 * np.sin(np.radians(-60))),
               (r2 * 0.7, -board_r * 0.8),
               f"strip = {a_strip:.2f}")

        dim_board(ax, -board_r, board_r, -board_r, board_r, pad_frac=0.08)

        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"], "Substrate"),
            (LAYER_COLORS["copper"], "Spiral arm 1"),
            ("#cc7733", "Spiral arm 2 (180°)"),
        ], loc="lower left")
        ax.margins(0.12)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "Active radius vs frequency", grid=True,
                 equal=False)
        f = np.logspace(np.log10(r["f_low"]) - 0.05,
                        np.log10(r["f_high"]) + 0.05, 200)
        r_active = C_LIGHT / (2 * np.pi * f)
        m = ctx.out_mult
        ax.plot(f / 1e9, r_active * m, color="#00FFCC", lw=2)
        ax.fill_between(f / 1e9, 0, r_active * m, color="#00FFCC", alpha=0.20)
        ax.axhline(r["r1"] * m, ls=":", color="#888", label=f"r₁ = {r['r1']*m:.2f}")
        ax.axhline(r["r2"] * m, ls=":", color="#888", label=f"r₂ = {r['r2']*m:.2f}")
        ax.axvspan(r["f_low"]/1e9, r["f_high"]/1e9,
                   color="#00FFCC", alpha=0.10, label="Useful band")
        ax.set_xscale("log")
        ax.set_xlabel("Frequency (GHz)", color=LAYER_COLORS["text"])
        ax.set_ylabel(f"Active-ring radius λ/(2π) [{ctx.unit_str}]",
                      color=LAYER_COLORS["text"])
        ax.legend(loc="upper right", facecolor=LAYER_COLORS["panel_bg"],
                  edgecolor=LAYER_COLORS["axis"],
                  labelcolor=LAYER_COLORS["text"], fontsize=9)

    def pattern(self, theta, phi, ctx, r):
        # Broadside cardioid: cos(θ)^2 above ground, with a soft floor for
        # the bidirectional planar (no-cavity) case.
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        up   = np.clip(np.cos(theta_b), 0.0, None) ** 1.5
        down = 0.55 * np.clip(-np.cos(theta_b), 0.0, None) ** 1.5
        return up + down
