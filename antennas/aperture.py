"""
Aperture antennas — rectangular slot, bowtie, Vivaldi, pyramidal horn.
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches
from matplotlib.path import Path as MPath

from .base import AntennaBase, Context, Input, register_antenna, C_LIGHT, ETA0
from calculators import microstrip
from plotting.cad import (
    LAYER_COLORS, style_ax, dim_horizontal, dim_vertical, dim_linear,
    angle_dim, leader, add_layer_legend,
)


# ============================================================================
# Rectangular Slot
# ============================================================================

@register_antenna("Rectangular Slot", category="Aperture")
class RectangularSlot(AntennaBase):
    notes = "Booker's complementary relation: Z_slot · Z_dipole = η₀²/4."

    def inputs(self):
        return [
            Input("slot_W", "Slot width (units)", "2.0"),
        ]

    def compute(self, ctx, params):
        W = float(params.get("slot_W", "2.0")) * 1e-3
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
                "W_feed": feed["W"], "Ereff": ereff}

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
        dim_horizontal(ax, -L/2, L/2, W/2 + Ws*0.4, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -W/2, W/2, -L/2 - Ls*0.4, f"W = {W:.2f}", offset=0)
        dim_horizontal(ax, 0, off, -W/2 - Ws*0.1, f"offset = {off:.2f}",
                       offset=0, color=LAYER_COLORS["dim_alt"])
        add_layer_legend(ax, [
            (LAYER_COLORS["copper"], "Ground plane"),
            (LAYER_COLORS["substrate"], "Slot aperture"),
            ("cyan", "Feed (opposite side)"),
        ], loc="upper right")
        ax.margins(0.12)

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
        return {"L": L, "W": W, "flare": flare, "Z_in": Z_in}

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
        dim_horizontal(ax, -L/2, L/2, -W/2 - Ws*0.4, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -W/2, W/2, L/2 + Ls*0.4, f"W = {W:.2f}", offset=0)
        angle_dim(ax, (0, 0), (L/2, W/2), (L/2, -W/2),
                  f"{r['flare']:.0f}°",
                  radius=L * 0.18, color=LAYER_COLORS["dim_special"])
        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"], "Substrate"),
            (LAYER_COLORS["copper"], "Copper"),
        ], loc="lower left")
        ax.margins(0.1)

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
            Input("feed_side",  "SMA connector side (left / bottom)", "left",
                  tooltip="Board edge the SMA sits on. 'left' = same side as the "
                          "cavity; microstrip L-turns on the bottom layer to "
                          "cross the slot perpendicular."),
            Input("margin_back","Board margin behind cavity", "4.0", unit="units"),
            Input("margin_side","Board margin beside taper", "4.0", unit="units"),
        ]

    @staticmethod
    def _to_m(s, default_m):
        try:
            v = float(s)
        except (TypeError, ValueError):
            return default_m
        return default_m if v <= 0 else v * 1e-3

    def compute(self, ctx, params):
        fL = float(params.get("f_low_GHz",  "2.0")) * 1e9
        fH = float(params.get("f_high_GHz", "10.0")) * 1e9
        if fH <= fL:
            fH = fL * 2

        L = float(params.get("length", "80.0")) * 1e-3          # taper length
        # Auto defaults: W_ap = λ_low/2, w0 = λ_high/30
        W_ap_default = 0.5 * C_LIGHT / fL
        w0_default   = (C_LIGHT / fH) / 30.0
        W_ap = self._to_m(params.get("W_ap"), W_ap_default)
        w0   = self._to_m(params.get("w0"),   w0_default)
        if w0 >= W_ap:
            w0 = W_ap * 0.05

        # Exponential taper rate so y(L) = W_ap/2 starting from y(0) = w0/2
        R = np.log(W_ap / w0) / L

        # Microstrip feed (balun) — uses ctx.fr as the design/center freq
        feed = microstrip.synthesize(ctx.z0, ctx.er, ctx.h)
        # Slotline guide wavelength (rough): εr_slot ≈ (εr + 1)/2
        er_slot = (ctx.er + 1) / 2
        lam_g_slot_at_fr   = C_LIGHT / (ctx.fr * np.sqrt(er_slot))
        lam_g_slot_at_fL   = C_LIGHT / (fL   * np.sqrt(er_slot))
        lam_g_strip        = C_LIGHT / (ctx.fr * np.sqrt(feed["Ereff"]))

        # Feed crosses the slotline at λ_g_slot/4 from cavity center — this
        # maximizes bandwidth of the balun.
        feed_cross_x = lam_g_slot_at_fr / 4

        cavity_dia = self._to_m(params.get("cavity_dia"),
                                lam_g_slot_at_fL / 3)
        stub_ratio = float(params.get("stub_ratio", "0.25"))
        stub_angle = float(params.get("stub_angle", "45"))
        stub_len   = stub_ratio * lam_g_strip
        feed_Z     = float(params.get("feed_Z", "50"))
        feed_side  = str(params.get("feed_side", "left")).strip().lower()
        if feed_side not in ("left", "bottom"):
            feed_side = "left"
        m_back     = float(params.get("margin_back", "4.0")) * 1e-3
        m_side     = float(params.get("margin_side", "4.0")) * 1e-3

        # Quick sanity checks
        warn = []
        if L < 0.8 * (C_LIGHT / fL):
            warn.append(f"L < 0.8·λ_low ({(C_LIGHT/fL)*1e3:.1f} mm); gain will be low.")
        if W_ap < 0.45 * (C_LIGHT / fL):
            warn.append(f"W_ap < λ_low/2; poor low-freq response.")
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
            "warnings": warn,
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        gain_dbi = 8 + 2 * np.log10(max(r["L"] * ctx.fr / C_LIGHT, 0.2))
        out = [
            f"  Band              = {r['f_low']/1e9:.2f}–{r['f_high']/1e9:.2f} GHz",
            f"  Taper length L    = {r['L']*m:.2f} {u}  ({r['L']*r['f_low']/C_LIGHT:.2f} λ_low)",
            f"  Aperture W_ap     = {r['W_ap']*m:.2f} {u}  ({r['W_ap']/(0.5*C_LIGHT/r['f_low']):.2f}·λ_low/2)",
            f"  Throat w₀         = {r['w0']*m:.3f} {u}",
            f"  Taper rate R      = {r['R_rate']/1e3:.4f} / {u}",
            f"  Back-cavity Ø     = {r['cavity_dia']*m:.2f} {u}",
            f"  Feed ↦ slotline   = {r['feed_cross_x']*m:.2f} {u} from cavity  (λ_g_slot/4 @ fr)",
            f"  Microstrip W      = {r['W_feed']*m:.3f} {u}  (Z₀={r['feed_Z']:.0f} Ω, εr_eff={r['Ereff_feed']:.2f})",
            f"  Radial stub       = r={r['stub_len']*m:.2f} {u}  ({r['stub_angle_deg']:.0f}° sector)",
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
        Rm = r["R_rate"] / 1e3    # 1 / display-unit
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

        # Board footprint: x from (-cavity-margin_back) to (+L  — aperture open to board edge!)
        x_left  = -2 * cav_r - mb
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
        # Cavity center at (-cav_r, 0) so cavity tangentially meets throat at x=0.
        cav_cx = -cav_r
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

        # Radial stub sector (same on both layouts) — opens upward from crossing
        theta_c = np.pi / 2
        ang_s = np.linspace(theta_c - stub_half, theta_c + stub_half, 60)
        stub_pts = [(feed_x, 0.0)]
        stub_pts += [(feed_x + stub_len * np.cos(a), stub_len * np.sin(a))
                     for a in ang_s]
        stub_pts.append((feed_x, 0.0))

        if feed_side == "left":
            # Horizontal run from left edge to feed_x, then 90° up to cross slot
            ax.plot([x_left, feed_x], [y_run, y_run], ls="--",
                    lw=max(wf, 0.6), color="#1de9ff", alpha=0.85, zorder=4)
            ax.plot([feed_x, feed_x], [y_run, 0.0], ls="--",
                    lw=max(wf, 0.6), color="#1de9ff", alpha=0.85, zorder=4)
            # SMA footprint at left edge
            ax.add_patch(mpatches.Circle((x_left, y_run), sma_r,
                                         fill=False, ls=":", ec="#1de9ff",
                                         lw=1.0, zorder=4))
            ax.text(x_left, y_run - sma_r*1.4, "SMA", color="#1de9ff",
                    ha="center", va="top", fontsize=8, zorder=5)
        else:  # "bottom"
            ax.plot([feed_x, feed_x], [y_bot, 0.0], ls="--",
                    lw=max(wf, 0.6), color="#1de9ff", alpha=0.85, zorder=4)
            ax.add_patch(mpatches.Circle((feed_x, y_bot), sma_r,
                                         fill=False, ls=":", ec="#1de9ff",
                                         lw=1.0, zorder=4))
            ax.text(feed_x + sma_r*1.4, y_bot, "SMA", color="#1de9ff",
                    ha="left", va="center", fontsize=8, zorder=5)

        ax.add_patch(mpatches.Polygon(
            stub_pts, closed=True, facecolor="#1de9ff22",
            edgecolor="#1de9ff", lw=1.1, ls="--", zorder=4))

        # ---- Dimensions ----
        # Envelope
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
        Rm = r["R_rate"] / 1e3
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

    def inputs(self):
        return [
            Input("a_wg", "WG a (broad wall, units)", "22.86",
                  tooltip="WR-90 default (22.86 mm for X-band)"),
            Input("b_wg", "WG b (narrow wall, units)", "10.16"),
            Input("gain_dBi_target", "Target gain (dBi)", "15"),
        ]

    def compute(self, ctx, params):
        a_wg = float(params.get("a_wg", "22.86")) * 1e-3
        b_wg = float(params.get("b_wg", "10.16")) * 1e-3
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
                "Gain_dBi": 10 * np.log10(G_lin), "Ereff": 1.0}

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
