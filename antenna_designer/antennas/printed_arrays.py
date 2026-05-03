"""
Printed-circuit array antennas.

  * Microstrip Quasi-Yagi  —  printed reflector + dipole + directors, microstrip-
    to-CPS balun, truncated ground plane (Kaneda / Deal / Itoh topology).
  * Printed LPDA           —  log-periodic dipole array with alternating arms on
    top/bottom layers fed by a pair of parallel transmission-line tracks.
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches
from matplotlib.path import Path
from matplotlib.patches import PathPatch

from .base import AntennaBase, Context, Input, register_antenna, C_LIGHT, ETA0
from calculators import microstrip
from plotting.cad import (
    LAYER_COLORS, style_ax, dim_horizontal, dim_vertical,
    leader, add_layer_legend,
)


# Colors for bottom-layer copper (shown semi-transparent / hatched on top view)
_BOT_FACE = "#7a6030"     # darker bronze for bottom copper
_BOT_EDGE = "#5a461e"


# ============================================================================
# Microstrip Quasi-Yagi
# ============================================================================

@register_antenna("Microstrip Quasi-Yagi", category="Patch")
class MicrostripQuasiYagi(AntennaBase):
    notes = ("Planar Yagi on PCB: truncated ground plane acts as the reflecting "
             "element; microstrip-to-CPS balun drives the printed dipole; "
             "printed directors on top layer. Topology after Kaneda-Qian-Itoh "
             "(IEEE MTT 2002). Enter physical dimensions in mm.")

    def inputs(self):
        return [
            Input("n_dirs",     "Number of directors", "3"),
            Input("L_drvn",     "Driven dipole arm length (each, 0 = auto)", "0.0", unit="units"),
            Input("L_dir",      "Director length (0 = auto)", "0.0", unit="units"),
            Input("s_drvn_dir", "Driven → first director (0 = auto)", "0.0", unit="units"),
            Input("s_dir",      "Director-to-director spacing (0 = auto)", "0.0", unit="units"),
            Input("s_ref_drvn", "Reflector (gnd edge) → driven (0 = auto)", "0.0", unit="units"),
            Input("W_strip",    "Printed strip width", "2.0", unit="units"),
            Input("W_feed",     "Microstrip feed width (0 = auto Z0=50 Ω)", "0.0", unit="units"),
            Input("W_cps",      "CPS track width (balun)", "1.5", unit="units"),
            Input("gap_cps",    "CPS gap (balun)", "1.0", unit="units"),
            Input("margin",     "Board margin beyond outer elements", "4.0", unit="units"),
        ]

    # ---- sizing ----------------------------------------------------
    def compute(self, ctx, params):
        lam0 = ctx.lambda0
        # Effective λ for printed dipole — use (εr+1)/2 approximation
        eps_eff_strip = (ctx.er + 1) / 2
        lam_g = lam0 / np.sqrt(eps_eff_strip)

        n_dirs = max(0, int(float(params.get("n_dirs", "3"))))

        def _val(key, default_m):
            v = float(params.get(key, "0")) * 1e-3  # input in mm-ish "units" == mm when out_mult=1e3
            return v if v > 0 else default_m

        # Auto defaults
        L_drvn_arm = _val("L_drvn", 0.21 * lam_g)         # each arm ≈ 0.21 λg  → total ~0.42 λg (printed dipole is slightly shorter than λ/2 due to fringing)
        L_dir      = _val("L_dir",  0.38 * lam_g)         # total director length ≈ 0.38 λg
        s_drvn_dir = _val("s_drvn_dir", 0.17 * lam_g)
        s_dir      = _val("s_dir",  0.17 * lam_g)
        s_ref_drvn = _val("s_ref_drvn", 0.22 * lam_g)     # distance from gnd edge to driven
        W_strip    = _val("W_strip", 0.008 * lam0)        # cosmetic line width
        W_cps      = _val("W_cps", 0.012 * lam0)
        gap_cps    = _val("gap_cps", 0.010 * lam0)
        margin     = _val("margin", 0.05 * lam0)

        # Microstrip feed synthesis
        W_feed_input = float(params.get("W_feed", "0.0")) * 1e-3
        if W_feed_input > 0:
            W_feed = W_feed_input
            ms = microstrip.analyze(W_feed, ctx.er, ctx.h)
            Z0_feed = ms["Z0"]
            er_feed = ms["Ereff"]
        else:
            ms = microstrip.synthesize(ctx.z0, ctx.er, ctx.h)
            W_feed = ms["W"]
            Z0_feed = ms["Z0"]
            er_feed = ms["Ereff"]
        lam_feed = lam0 / np.sqrt(er_feed)

        # Layout — x goes from left (feed edge) to right (directors)
        # Ground plane ends at x_gnd_end = 0.0 (truncated edge = reflector).
        # Driven dipole at x_drvn = s_ref_drvn.  Balun shows as a short
        # microstrip stub on the bottom layer perpendicular to the feed at the
        # ground-plane edge.
        L_balun = 0.25 * lam_feed          # ≈ λg/4 open-circuit stub
        x_drvn  = s_ref_drvn               # gap from gnd edge to driven dipole

        # Director positions
        x_dirs = [x_drvn + s_drvn_dir + i * s_dir for i in range(n_dirs)]

        # Board extents — keep the feed run short (one feed-line width of
        # extra ground plus the user margin is plenty; the long ground
        # cliff that looks empty in CAD was misleading).
        ground_behind = max(margin, 3.0 * W_feed)
        x_left  = -(ground_behind + margin * 0.5)
        x_right = (x_dirs[-1] if x_dirs else x_drvn) + margin
        y_ext   = max(L_drvn_arm, 0.5 * L_dir) + margin
        y_top   =  y_ext
        y_bot   = -y_ext

        # Ground plane ends at x_gnd_end (truncated)
        x_gnd_end = 0.0   # balun section boundary

        # Gain estimate
        N_total = 1 + 1 + n_dirs   # reflector (gnd) + driven + directors
        gain_est = 6.0 + 2.3 * np.log10(max(N_total, 2))

        return {
            "lam0": lam0, "lam_g": lam_g, "lam_feed": lam_feed,
            "n_dirs": n_dirs,
            "L_drvn_arm": L_drvn_arm, "L_dir": L_dir,
            "s_drvn_dir": s_drvn_dir, "s_dir": s_dir, "s_ref_drvn": s_ref_drvn,
            "W_strip": W_strip, "W_feed": W_feed, "W_cps": W_cps, "gap_cps": gap_cps,
            "L_balun": L_balun,
            "x_drvn": x_drvn, "x_dirs": x_dirs,
            "x_left": x_left, "x_right": x_right, "y_top": y_top, "y_bot": y_bot,
            "x_gnd_end": x_gnd_end,
            "Z0_feed": Z0_feed, "er_feed": er_feed,
            "gain_dBi_est": gain_est, "margin": margin,
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        lines = [
            f"  λ₀              = {r['lam0']*m:.2f} {u}",
            f"  λ_g (strip)     = {r['lam_g']*m:.2f} {u}   (ε_eff ≈ {(ctx.er+1)/2:.2f})",
            f"  λ_g (feed MS)   = {r['lam_feed']*m:.2f} {u}   (ε_eff = {r['er_feed']:.2f})",
            "",
            f"  Driven arm L    = {r['L_drvn_arm']*m:.2f} {u}   (total dipole = {2*r['L_drvn_arm']*m:.2f})",
            f"  Director L      = {r['L_dir']*m:.2f} {u}",
            f"  # directors     = {r['n_dirs']}",
            f"  Strip width     = {r['W_strip']*m:.2f} {u}",
            "",
            f"  Gnd-edge → drvn = {r['s_ref_drvn']*m:.2f} {u}   (≈ λ_g/4)",
            f"  Drvn → dir 1    = {r['s_drvn_dir']*m:.2f} {u}",
            f"  Dir spacing     = {r['s_dir']*m:.2f} {u}",
            "",
            f"  Feed MS W       = {r['W_feed']*m:.2f} {u}   (Z₀ = {r['Z0_feed']:.1f} Ω)",
            f"  Balun length    = {r['L_balun']*m:.2f} {u}   (λ_feed/4)",
            f"  CPS: w = {r['W_cps']*m:.2f}  gap = {r['gap_cps']*m:.2f} {u}",
            "",
            f"  Estimated gain  ≈ {r['gain_dBi_est']:.1f} dBi",
        ]
        return lines

    # ---- plotting --------------------------------------------------
    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        style_ax(ax.figure, ax, "Microstrip Quasi-Yagi", equal=True)

        # Scale everything to display units
        x_left  = r["x_left"]  * m
        x_right = r["x_right"] * m
        y_top   = r["y_top"]   * m
        y_bot   = r["y_bot"]   * m
        x_gnd_end = r["x_gnd_end"] * m
        x_drvn  = r["x_drvn"]  * m
        L_arm   = r["L_drvn_arm"] * m
        L_dir   = r["L_dir"]   * m
        W_strip = r["W_strip"] * m
        W_cps   = r["W_cps"]   * m
        gap_cps = r["gap_cps"] * m
        W_feed  = r["W_feed"]  * m
        L_balun = r["L_balun"] * m
        margin  = r["margin"]  * m

        # 1) Substrate rectangle
        ax.add_patch(mpatches.Rectangle(
            (x_left, y_bot), x_right - x_left, y_top - y_bot,
            facecolor=LAYER_COLORS["substrate"], edgecolor=None, zorder=0))

        # 2) Bottom-layer ground plane (truncated) — shown as a darker patch
        ax.add_patch(mpatches.Rectangle(
            (x_left, y_bot), x_gnd_end - x_left, y_top - y_bot,
            facecolor=_BOT_FACE, edgecolor=_BOT_EDGE, lw=0.8,
            alpha=0.75, hatch="////", zorder=1))

        # 3) Bottom-layer microstrip feed (goes from left board edge to balun T)
        # Center the feed at y=0 in the balun section
        y_feed = 0.0
        ax.add_patch(mpatches.Rectangle(
            (x_left, y_feed - W_feed/2), x_gnd_end - x_left, W_feed,
            facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
            lw=0.7, zorder=3))

        # 4) Microstrip-to-CPS balun — a quarter-wave stub + T junction.
        #    Cosmetic representation: T from feed to two CPS tracks that diverge
        #    to feed the two dipole arms.
        # CPS section: two parallel tracks running from x_gnd_end to x_drvn
        y_cps_u =  (gap_cps/2 + W_cps/2)
        y_cps_l = -(gap_cps/2 + W_cps/2)
        # Balun stub — perpendicular open-circuit stub at x_gnd_end, on bottom layer
        stub_len = L_balun * 0.9
        ax.add_patch(mpatches.Rectangle(
            (x_gnd_end - W_feed/2, -stub_len), W_feed, stub_len,
            facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
            lw=0.7, zorder=3))
        # CPS tracks on top layer (from balun T to driven dipole)
        for yc in (y_cps_u, y_cps_l):
            ax.add_patch(mpatches.Rectangle(
                (x_gnd_end, yc - W_cps/2), x_drvn - x_gnd_end, W_cps,
                facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
                lw=0.7, zorder=3))

        # 5) Driven dipole — two printed arms extending from CPS tracks
        # Upper arm: from top edge of upper CPS track up to +L_arm
        ax.add_patch(mpatches.Rectangle(
            (x_drvn - W_strip/2, y_cps_u + W_cps/2), W_strip, L_arm,
            facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
            lw=0.7, zorder=5))
        # Lower arm: from bottom edge of lower CPS track down by L_arm
        ax.add_patch(mpatches.Rectangle(
            (x_drvn - W_strip/2, y_cps_l - W_cps/2 - L_arm), W_strip, L_arm,
            facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
            lw=0.7, zorder=5))

        # 6) Directors — top-layer strips centered on y=0
        for i, xd in enumerate(r["x_dirs"]):
            xdm = xd * m
            ax.add_patch(mpatches.Rectangle(
                (xdm - W_strip/2, -L_dir/2), W_strip, L_dir,
                facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
                lw=0.7, zorder=4))
            ax.text(xdm, L_dir/2 + margin*0.15, f"D{i+1}",
                    ha="center", va="bottom", fontsize=8,
                    color=LAYER_COLORS["text"])

        # 7) SMA marker at left edge of board on the microstrip feed
        sma_r = max(W_feed * 1.2, margin * 0.3)
        ax.add_patch(mpatches.Circle((x_left, y_feed), sma_r, fill=False,
            edgecolor=LAYER_COLORS["dim"], lw=1.0, ls=":", zorder=6))
        ax.text(x_left, y_feed - sma_r * 1.4, "SMA",
                ha="center", va="top", fontsize=8,
                color=LAYER_COLORS["dim"])

        # Labels
        ax.text((x_left + x_gnd_end)/2, y_bot + (y_top - y_bot)*0.04,
                "Truncated ground (bottom layer — acts as reflector)",
                ha="center", va="bottom", fontsize=8, color=LAYER_COLORS["text"],
                alpha=0.75)

        # Dimensions
        #   L_arm: placed to the LEFT of the driven dipole so it doesn't cover the arm.
        dim_vertical(ax, y_cps_u + W_cps/2, y_cps_u + W_cps/2 + L_arm,
                     x_drvn - margin*0.8,
                     f"L_arm={L_arm:.2f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        #   L_dir: placed to the RIGHT of the last director
        x_last_dir = (r["x_dirs"][-1]*m if r["x_dirs"] else x_drvn + margin)
        dim_vertical(ax, -L_dir/2, L_dir/2,
                     x_last_dir + margin*0.45,
                     f"L_dir={L_dir:.2f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        #   s_ref above the CPS region, well clear of the top arm
        s_ref_y = y_cps_u + W_cps/2 + L_arm + margin*0.4
        dim_horizontal(ax, x_gnd_end, x_drvn, s_ref_y,
                       f"s_ref={x_drvn-x_gnd_end:.2f}", offset=0)
        if r["x_dirs"]:
            dim_horizontal(ax, x_drvn, r["x_dirs"][0]*m, s_ref_y,
                           f"s₁={r['x_dirs'][0]*m - x_drvn:.2f}", offset=0,
                           color=LAYER_COLORS["dim_alt"])
        #   s_dir between the first two directors (if ≥ 2 directors)
        if len(r["x_dirs"]) >= 2:
            s_dir_val = (r["x_dirs"][1] - r["x_dirs"][0]) * m
            dim_horizontal(ax, r["x_dirs"][0]*m, r["x_dirs"][1]*m,
                           -L_dir/2 - margin*0.35,
                           f"s_dir={s_dir_val:.2f}", offset=0,
                           color=LAYER_COLORS["dim_alt"])

        # Line-width leaders (W_feed / W_strip / CPS) for fabrication
        leader(ax, (x_left * 0.45, W_feed/2),
               (x_left * 0.45, y_top - margin*0.8),
               f"W_feed={W_feed:.2f}")
        # W_cps / gap — leader anchored just above the CPS, label placed
        # below the dipole arms to stay clear of the L_arm dimension line.
        cps_anchor_x = x_gnd_end + (x_drvn - x_gnd_end) * 0.25
        leader(ax, (cps_anchor_x, y_cps_u),
               (cps_anchor_x - margin*0.2, -L_arm * 0.35),
               f"W_cps={W_cps:.2f}\ngap={gap_cps:.2f}")
        leader(ax, (x_last_dir + W_strip/2, -L_dir/2 + L_dir*0.15),
               (x_last_dir + margin*1.2, -L_dir/2 - margin*0.1),
               f"W_strip={W_strip:.2f}")
        # Balun stub length (bottom-layer open stub below ground edge)
        dim_vertical(ax, -r["L_balun"]*m*0.9, 0.0,
                     x_gnd_end - W_feed, f"L_balun={r['L_balun']*m*0.9:.2f}",
                     offset=0, color=LAYER_COLORS["dim_special"])

        add_layer_legend(ax, loc="lower right", items=[
            (LAYER_COLORS["substrate"], "Substrate"),
            (LAYER_COLORS["copper"], "Top copper"),
            (_BOT_FACE, "Bottom ground (reflector)"),
        ])
        ax.margins(0.06)

    def plot_fields(self, ax, ctx, r):
        ax.text(0.5, 0.5, "Quasi-Yagi: end-fire along +x\n(see 3D / 2D Pattern tabs)",
                ha="center", va="center", transform=ax.transAxes,
                color=LAYER_COLORS["text"], fontsize=11)
        ax.set_axis_off()

    def pattern(self, theta, phi, ctx, r):
        # End-fire along +x, beam sharpness grows with director count.
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        phi_b = np.broadcast_to(phi, np.broadcast_shapes(theta.shape, phi.shape))
        cos_ax = np.sin(theta_b) * np.cos(phi_b)
        N = 1 + 1 + r["n_dirs"]
        sharp = 2.0 + 0.8 * (N - 3)
        F = np.clip(cos_ax, 0, None) ** sharp
        back = 0.10 * np.clip(-cos_ax, 0, None) ** 2
        # Printed dipole element factor (|cosφ| in E-plane) — weak modulation
        elem = np.abs(np.cos(0.5 * np.pi * np.clip(np.cos(theta_b), -1, 1)))
        return (F + back) * elem


# ============================================================================
# Printed LPDA (log-periodic dipole array)
# ============================================================================

@register_antenna("Printed LPDA (PCB)", category="Patch")
class PrintedLPDA(AntennaBase):
    notes = ("Log-periodic dipole array printed on a two-layer PCB. Twin-track "
             "transmission line runs the length of the board; each dipole has "
             "one arm on the top layer and one on the bottom, alternating every "
             "element for the required 180° phase reversal. The coaxial feed "
             "enters at the LARGE-element end of the boom (infinite-balun "
             "construction: coax shield is soldered along the bottom-layer "
             "twin-track; the centre pin transitions to the top-layer track). "
             "The main beam radiates end-fire toward the SMALL-element end. "
             "Enter τ and σ to control scaling / spacing.")

    def inputs(self):
        return [
            Input("f_low_GHz",  "Low frequency (GHz)",  "1.0"),
            Input("f_high_GHz", "High frequency (GHz)", "3.0"),
            Input("tau",        "Scaling ratio τ (0.80–0.95)", "0.88"),
            Input("sigma",      "Relative spacing σ (0.12–0.22)", "0.16"),
            Input("W_strip",    "Dipole arm strip width", "2.0", unit="units"),
            Input("W_track",    "Twin-track width", "1.5", unit="units"),
            Input("gap_track",  "Twin-track gap", "1.0", unit="units"),
            Input("margin",     "Board margin", "4.0", unit="units"),
        ]

    def compute(self, ctx, params):
        fL  = float(params.get("f_low_GHz",  "1.0")) * 1e9
        fH  = float(params.get("f_high_GHz", "3.0")) * 1e9
        tau = float(params.get("tau",   "0.88"))
        sig = float(params.get("sigma", "0.16"))
        W_strip = float(params.get("W_strip", "2.0")) * 1e-3
        W_track = float(params.get("W_track", "1.5")) * 1e-3
        gap_track = float(params.get("gap_track", "1.0")) * 1e-3
        margin = float(params.get("margin", "4.0")) * 1e-3

        # Printed dipole on PCB radiates at slightly lower frequency than in air
        # → arm length shorter by sqrt(er_eff). Use εr_eff ≈ (εr+1)/2 (half-space).
        eps_eff = (ctx.er + 1) / 2.0
        # Longest dipole: total length L1 ≈ 0.46·λ0/√εr_eff at fL (printed dipole)
        # Use boundary factor 1.05 to guarantee coverage:
        bar = 1.05
        L1 = (0.46 * bar) * (C_LIGHT / fL) / np.sqrt(eps_eff)
        # Shortest must be ≤ 0.46·λ/√εr_eff at fH
        LN_min = 0.46 * (C_LIGHT / fH) / np.sqrt(eps_eff)
        N = int(np.ceil(1 + np.log(LN_min / L1) / np.log(tau)))
        N = max(N, 5)

        lengths = [L1 * tau ** n for n in range(N)]        # L_1 (longest, back) → L_N (shortest, front)
        # Carrel spacing: d_n = 2σ·L_n (distance from dipole n to n+1)
        spacings = [2 * sig * lengths[n] for n in range(N - 1)]
        # Positions along boom — element 1 at x=0, element n at cumulative spacing
        positions = [0.0]
        for s in spacings:
            positions.append(positions[-1] + s)
        boom = positions[-1]

        # Gain estimate (Carrel): slight fit
        gain = 7.0 + 35.0 * sig * tau

        # Board extents (feed at the short-dipole end, at x = boom + margin)
        x_left  = -margin
        x_right = boom + margin
        y_ext   = L1 / 2 + margin
        y_top   =  y_ext
        y_bot   = -y_ext

        return {
            "tau": tau, "sigma": sig, "N": N, "eps_eff": eps_eff,
            "f_low": fL, "f_high": fH,
            "lengths": lengths, "spacings": spacings, "positions": positions,
            "boom": boom, "gain_dBi_est": gain,
            "W_strip": W_strip, "W_track": W_track, "gap_track": gap_track,
            "margin": margin,
            "x_left": x_left, "x_right": x_right,
            "y_top": y_top, "y_bot": y_bot,
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Band             = {r['f_low']/1e9:.2f} – {r['f_high']/1e9:.2f} GHz",
            f"  τ = {r['tau']:.3f},  σ = {r['sigma']:.3f},  N = {r['N']}",
            f"  ε_eff (printed) ≈ {r['eps_eff']:.3f}",
            f"  Longest dipole   = {r['lengths'][0]*m:.2f} {u}",
            f"  Shortest dipole  = {r['lengths'][-1]*m:.2f} {u}",
            f"  Boom length      = {r['boom']*m:.2f} {u}",
            f"  Strip width      = {r['W_strip']*m:.2f} {u}",
            f"  Twin-track       = {r['W_track']*m:.2f} {u}  (gap {r['gap_track']*m:.2f})",
            f"  Estimated gain   = {r['gain_dBi_est']:.1f} dBi",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        style_ax(ax.figure, ax, f"Printed LPDA — {r['N']} dipoles", equal=True)

        # Scale display units
        x_left  = r["x_left"]  * m
        x_right = r["x_right"] * m
        y_top   = r["y_top"]   * m
        y_bot   = r["y_bot"]   * m
        W_strip = r["W_strip"] * m
        W_track = r["W_track"] * m
        gap_tr  = r["gap_track"] * m
        margin  = r["margin"]  * m
        lengths = [L * m for L in r["lengths"]]
        positions = [p * m for p in r["positions"]]
        boom = r["boom"] * m

        # 1) Substrate
        ax.add_patch(mpatches.Rectangle(
            (x_left, y_bot), x_right - x_left, y_top - y_bot,
            facecolor=LAYER_COLORS["substrate"], edgecolor=None, zorder=0))

        # 2) Twin-track feedline: top track at +gap/2..+gap/2+W_track, bottom at -gap/2..-gap/2-W_track
        y_top_trk_lo =  gap_tr / 2
        y_top_trk_hi =  gap_tr / 2 + W_track
        y_bot_trk_hi = -gap_tr / 2
        y_bot_trk_lo = -gap_tr / 2 - W_track

        # Top-layer track (orange)
        ax.add_patch(mpatches.Rectangle(
            (0.0, y_top_trk_lo), boom, W_track,
            facecolor=LAYER_COLORS["copper"], edgecolor=LAYER_COLORS["copper_edge"],
            lw=0.7, zorder=3))
        # Bottom-layer track (bronze hatched)
        ax.add_patch(mpatches.Rectangle(
            (0.0, y_bot_trk_lo), boom, W_track,
            facecolor=_BOT_FACE, edgecolor=_BOT_EDGE, lw=0.7,
            hatch="////", alpha=0.85, zorder=3))

        # 3) Dipole arms — alternating layers.
        #    Element n=0 (longest) → upper arm TOP copper, lower arm BOTTOM.
        #    n=1 flips (upper BOTTOM, lower TOP); thereafter alternating.
        for n, (xn, Ln) in enumerate(zip(positions, lengths)):
            half = Ln / 2
            flip = (n % 2 == 1)
            upper_color = _BOT_FACE if flip else LAYER_COLORS["copper"]
            upper_edge  = _BOT_EDGE if flip else LAYER_COLORS["copper_edge"]
            upper_hatch = "////" if flip else None
            lower_color = LAYER_COLORS["copper"] if flip else _BOT_FACE
            lower_edge  = LAYER_COLORS["copper_edge"] if flip else _BOT_EDGE
            lower_hatch = None if flip else "////"

            # Upper arm: from top edge of upper twin-track up to +half
            ax.add_patch(mpatches.Rectangle(
                (xn - W_strip/2, y_top_trk_hi), W_strip, half - y_top_trk_hi,
                facecolor=upper_color, edgecolor=upper_edge,
                lw=0.7, hatch=upper_hatch,
                alpha=(0.85 if flip else 1.0), zorder=4))
            # Lower arm: from -half up to bottom edge of lower twin-track
            ax.add_patch(mpatches.Rectangle(
                (xn - W_strip/2, -half), W_strip,
                y_bot_trk_hi - (-half),
                facecolor=lower_color, edgecolor=lower_edge,
                lw=0.7, hatch=lower_hatch,
                alpha=(0.85 if not flip else 1.0), zorder=4))

        # 4) SMA at the LARGE-element end (left side — infinite-balun feed).
        #    The coax shield bonds to the bottom-layer track along the full
        #    length of the boom; the centre pin jumps up to the top track.
        #    Draw the SMA below the boom so it doesn't collide with L₁.
        sma_x = x_left
        sma_y = y_bot + (y_top - y_bot) * 0.28
        sma_r = max(W_track * 1.5, margin * 0.25)
        ax.add_patch(mpatches.Circle((sma_x, sma_y), sma_r, fill=False,
            edgecolor=LAYER_COLORS["dim"], lw=1.0, ls=":", zorder=6))
        # Dashed lead representing coax centre-pin routing up to the top track.
        ax.plot([sma_x, 0.0, 0.0],
                [sma_y, sma_y, 0.0],
                color=LAYER_COLORS["dim"], lw=1.0, ls="--", zorder=5)
        ax.text(sma_x, sma_y - sma_r * 1.3, "SMA\n(infinite balun)",
                ha="center", va="top", fontsize=8,
                color=LAYER_COLORS["dim"])

        # 5) Dimensions — keep clear of geometry
        #   L₁ labelled to the LEFT of element 1, above the SMA.
        dim_vertical(ax, -lengths[0]/2, lengths[0]/2, -margin*0.6,
                     f"L₁={lengths[0]:.1f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        #   L_N to the right of the short-dipole end
        dim_vertical(ax, -lengths[-1]/2, lengths[-1]/2,
                     positions[-1] + margin*0.55,
                     f"L_N={lengths[-1]:.1f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        dim_horizontal(ax, 0, boom, y_bot + margin*0.35,
                       f"Boom = {boom:.1f}", offset=0)
        # First-spacing dimension so τ / σ scaling is tangible.
        if len(positions) >= 2:
            dim_horizontal(ax, positions[0], positions[1],
                           y_top - margin*0.35,
                           f"d₁₂ = {positions[1]-positions[0]:.1f}",
                           offset=0, color=LAYER_COLORS["dim_alt"])
        # Twin-track width / gap via short leader labels
        leader(ax, (boom*0.5, y_top_trk_hi),
               (boom*0.5, y_top + margin*0.25),
               f"W_track={W_track:.2f}")
        leader(ax, (boom*0.5, 0.0),
               (boom*0.5 + margin*0.8, -margin*0.25),
               f"gap={gap_tr:.2f}")

        # Direction-of-peak-gain arrow — points RIGHT toward small elements
        beam_y = y_top - margin * 0.1
        ax.annotate("main beam →",
                    xy=(x_right - margin*0.3, beam_y),
                    xytext=(x_right - margin*4.0, beam_y),
                    ha="left", va="center",
                    color=LAYER_COLORS["dim"], fontsize=9,
                    arrowprops=dict(arrowstyle="->",
                                     color=LAYER_COLORS["dim"], lw=1.2))

        add_layer_legend(ax, loc="lower right", items=[
            (LAYER_COLORS["substrate"], "Substrate"),
            (LAYER_COLORS["copper"], "Top copper"),
            (_BOT_FACE, "Bottom copper"),
        ])
        ax.margins(0.04)

    def plot_fields(self, ax, ctx, r):
        ax.text(0.5, 0.5,
                f"LPDA ({r['N']} dipoles) — end-fire toward short end\n"
                f"τ={r['tau']:.2f}, σ={r['sigma']:.2f}",
                ha="center", va="center", transform=ax.transAxes,
                color=LAYER_COLORS["text"], fontsize=11)
        ax.set_axis_off()

    def pattern(self, theta, phi, ctx, r):
        # Same qualitative pattern as wire LPDA — end-fire along +x (short end).
        theta_b = np.broadcast_to(theta, np.broadcast_shapes(theta.shape, phi.shape))
        phi_b = np.broadcast_to(phi, np.broadcast_shapes(theta.shape, phi.shape))
        cos_ax = np.sin(theta_b) * np.cos(phi_b)
        sharp = 2 + 0.5 * r["N"] / 8.0
        F = np.clip(cos_ax, 0, None) ** sharp
        back = 0.08 * np.clip(-cos_ax, 0, None) ** 2
        return F + back
