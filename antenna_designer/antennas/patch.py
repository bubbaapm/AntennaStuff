"""
Microstrip patch antennas: rectangular (edge-fed, rear-fed, stub-tuned),
circular (rear-fed), PIFA, 2×1 array.

All math from Balanis, *Antenna Theory* 4e, Chapter 14. Cavity model for
impedance, transmission-line model for dimensions.
"""
from __future__ import annotations
import numpy as np
from scipy import integrate, special
from matplotlib import patches as mpatches

from .base import AntennaBase, Context, Input, Curve, register_antenna, C_LIGHT, ETA0
from calculators import microstrip, coax
from plotting.cad import (
    LAYER_COLORS, style_ax, dim_horizontal, dim_vertical, dim_linear,
    dim_radial, dim_diameter, leader, add_layer_legend, dim_board,
)


# ============================================================================
# Shared dimension calculation
# ============================================================================

def _patch_dimensions(ctx: Context) -> dict:
    """Classic Balanis Eq 14-6/14-7/14-8. Returns W, L, Ereff, ΔL in meters."""
    W = (C_LIGHT / (2 * ctx.fr)) * np.sqrt(2 / (ctx.er + 1))
    Ereff = ((ctx.er + 1) / 2) + ((ctx.er - 1) / 2) * (1 + 12 * ctx.h / W) ** (-0.5)
    dL = 0.412 * ctx.h * ((Ereff + 0.3) * (W / ctx.h + 0.264)) / \
         ((Ereff - 0.258) * (W / ctx.h + 0.8))
    L = C_LIGHT / (2 * ctx.fr * np.sqrt(Ereff)) - 2 * dL
    return {"W": W, "L": L, "Ereff": Ereff, "dL": dL}


def _edge_resistance(L: float, W: float, k0: float) -> dict:
    """Numerically integrate self- and mutual-conductances (Balanis 14-12a/14-18a)."""
    def G1_integrand(theta):
        sin_t = np.sin(theta)
        cos_t = np.cos(theta)
        # handle sin→0 by limit (sinc-like)
        if abs(cos_t) < 1e-8:
            arg = k0 * W / 2
            term = arg ** 2 * sin_t ** 3
        else:
            x = (k0 * W / 2) * cos_t
            term = (np.sin(x) / cos_t) ** 2 * sin_t ** 3
        return term

    def G12_integrand(theta):
        return G1_integrand(theta) * special.j0(k0 * L * np.sin(theta))

    I1, _ = integrate.quad(G1_integrand, 0, np.pi, limit=80)
    I12, _ = integrate.quad(G12_integrand, 0, np.pi, limit=80)
    G1 = I1 / (120 * np.pi ** 2)
    G12 = I12 / (120 * np.pi ** 2)
    # Even-mode edge resistance (two radiating slots in phase)
    R_edge = 1.0 / (2 * (G1 + G12))
    return {"G1": G1, "G12": G12, "R_edge": R_edge}


def _patch_pattern(theta, phi, L_eff, W, k0, h):
    """Cavity-model far-field magnitude of a rectangular patch (Balanis 14-44).
    Patch lies in xy-plane with L along x, W along y, ground below z=0.
    """
    # Avoid div-by-zero at θ=0 or φ=0
    X = 0.5 * k0 * W * np.sin(theta) * np.sin(phi)
    Y = 0.5 * k0 * L_eff * np.sin(theta) * np.cos(phi)
    sinc_x = np.where(np.abs(X) < 1e-9, 1.0, np.sin(X) / np.where(X == 0, 1, X))
    cos_y = np.cos(Y)
    # Element pattern of the two-slot radiator — no cosθ, use half-space above ground
    element = np.abs(sinc_x * cos_y)
    # Above-ground constraint: |cosθ| for θ ∈ [0, π/2], zero below
    above = np.where(np.cos(theta) > 0, np.cos(theta), 0)
    # E-theta-like magnitude (mix of θ and φ components — textbook approximation)
    return element * above


# ============================================================================
# Rectangular Edge-Fed (Inset)
# ============================================================================

@register_antenna("Rectangular Patch — Inset (Edge-Fed)", category="Patch")
class RectPatchInset(AntennaBase):
    notes = "Inset cut y₀ from radiating edge; W_feed sized for target Z₀ microstrip."
    polarization = "linear  (E along the resonant L direction)"
    beam_axis = "broadside (+Z)"
    bandwidth_note = "narrowband (~2–5 %), scales with substrate h"

    def inputs(self):
        return [
            Input("inset_gap", "Inset gap to feed line (units)", "0.5",
                  tooltip="Air gap beside the feed line cutting into the patch"),
        ]

    def compute(self, ctx: Context, params: dict) -> dict:
        dims = _patch_dimensions(ctx)
        W, L, Ereff = dims["W"], dims["L"], dims["Ereff"]
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        imp = _edge_resistance(L, W, k0)
        R_edge = imp["R_edge"]

        if ctx.z0 <= R_edge:
            y0 = (L / np.pi) * np.arccos(np.sqrt(ctx.z0 / R_edge))
        else:
            y0 = 0.0
        feed = microstrip.synthesize(ctx.z0, ctx.er, ctx.h)
        W_feed = feed["W"]
        gap = ctx.m(params.get("inset_gap", "0.5"))

        # Clamp inset so we don't pass the center
        y0 = min(y0, L * 0.45)

        return {
            "W": W, "L": L, "Ereff": Ereff,
            "dL": dims["dL"], "R_edge": R_edge,
            "G1": imp["G1"], "G12": imp["G12"],
            "y0": y0, "W_feed": W_feed, "inset_gap": gap,
            "W_feed_Ereff": feed["Ereff"],
            "L_eff": L + 2 * dims["dL"],
            "board_size": (L + 2 * ctx.Ls, W + 2 * ctx.Ws),
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Patch W        = {r['W']*m:.4f} {u}",
            f"  Patch L        = {r['L']*m:.4f} {u}",
            f"  ΔL (fringing)  = {r['dL']*m:.4f} {u}",
            f"  εr_eff         = {r['Ereff']:.3f}",
            f"  R_edge         = {r['R_edge']:.1f} Ω",
            f"  Inset y0       = {r['y0']*m:.4f} {u}",
            f"  Feed width     = {r['W_feed']*m:.4f} {u}  (Z₀={ctx.z0:.1f} Ω)",
            f"  Feed ε_eff     = {r['W_feed_Ereff']:.3f}",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, W = r["L"] * m, r["W"] * m
        Ls, Ws = ctx.Ls * m, ctx.Ws * m
        y0, wf, gap = r["y0"] * m, r["W_feed"] * m, r["inset_gap"] * m

        style_ax(ax.figure, ax, "Rectangular Patch (Inset Edge-Fed)", equal=True)

        # Substrate (symmetric, feed extends to right edge)
        ax.add_patch(mpatches.Rectangle(
            (-L/2 - Ls, -W/2 - Ws), L + 2*Ls, W + 2*Ws,
            facecolor=LAYER_COLORS["substrate"],
            edgecolor=LAYER_COLORS["axis"], lw=0.7, zorder=1))
        # Patch copper
        ax.add_patch(mpatches.Rectangle(
            (-L/2, -W/2), L, W, facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=2))
        # Feed line — drawn BEFORE the inset notches so the notches carve from it too.
        # Runs from x = L/2 - y0 (inset into patch) all the way to x = L/2 + Ls
        # (substrate right edge), width wf.
        feed_start = L / 2 - y0
        feed_end   = L / 2 + Ls
        ax.add_patch(mpatches.Rectangle(
            (feed_start, -wf/2), feed_end - feed_start, wf,
            facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=3))
        # SMA marker at the substrate edge where the feed exits
        ax.add_patch(mpatches.Circle((feed_end, 0), wf * 1.4,
                                     fill=False, ls=":", ec=LAYER_COLORS["copper_edge"],
                                     lw=0.9, zorder=5))
        # Inset notches (substrate-colored cutouts on either side of the feed line,
        # inside the patch)
        ax.add_patch(mpatches.Rectangle(
            (feed_start, wf/2), y0, gap,
            facecolor=LAYER_COLORS["substrate"], zorder=4))
        ax.add_patch(mpatches.Rectangle(
            (feed_start, -wf/2 - gap), y0, gap,
            facecolor=LAYER_COLORS["substrate"], zorder=4))

        # Dimensions — feature dims close to the part, board outline pushed
        # outboard so the two layers don't fight for space.
        dim_horizontal(ax, -L/2, L/2, -W/2 - Ws*0.3, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -W/2, W/2, -L/2 - Ls*0.3, f"W = {W:.2f}", offset=0)
        dim_horizontal(ax, feed_start, L/2, W/2 + gap + wf*1.4,
                       f"y₀ = {y0:.2f}", offset=0,
                       color=LAYER_COLORS["dim_alt"])
        # W_f leader pointing to the feed line from above, so the vertical
        # text is no longer sitting on top of the copper trace.
        leader(ax, (feed_end - (feed_end - L/2)*0.25, wf/2),
               (feed_end + Ls*0.2, W/2 - Ws*0.2),
               f"W_f = {wf:.2f}", color=LAYER_COLORS["dim_alt"])
        leader(ax, (feed_start + y0/2, wf/2 + gap/2),
               (L/2 + Ls*0.6, W/2 + Ws*0.3),
               f"gap = {gap:.2f}")

        # Overall board outline (magenta, outboard of everything else)
        dim_board(ax, -L/2 - Ls, L/2 + Ls, -W/2 - Ws, W/2 + Ws,
                  pad_frac=0.12)

        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"], f"Substrate (εr={ctx.er:.2f}, h={ctx.h*m:.2f})"),
            (LAYER_COLORS["copper"], "Top copper"),
        ], loc="lower left")
        ax.margins(0.18)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "TM₁₀ Mode E-Field |Ez|", equal=True, grid=False)
        L, W = r["L"] * ctx.out_mult, r["W"] * ctx.out_mult
        X, Y = np.meshgrid(np.linspace(-L/2, L/2, 220),
                           np.linspace(-W/2, W/2, 180))
        Ez = np.cos(np.pi * (X + L/2) / L)
        im = ax.contourf(X, Y, np.abs(Ez), 60, cmap="magma")
        # surface current Jx ∝ sin(πx/L) — overlay as quiver
        xs = np.linspace(-L/2*0.9, L/2*0.9, 14)
        ys = np.linspace(-W/2*0.85, W/2*0.85, 8)
        Xq, Yq = np.meshgrid(xs, ys)
        Jx = np.sin(np.pi * (Xq + L/2) / L)
        Jy = np.zeros_like(Jx)
        ax.quiver(Xq, Yq, Jx, Jy, color="cyan", pivot="mid", alpha=0.9,
                  scale=22, width=0.0035)
        ax.plot([-L/2, L/2, L/2, -L/2, -L/2],
                [-W/2, -W/2, W/2, W/2, -W/2], "w-", lw=1.2)
        cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=LAYER_COLORS["text"])
        cb.set_label("Normalized |Ez|", color=LAYER_COLORS["text"])
        ax.set_xlabel(f"x ({ctx.unit_str})", color=LAYER_COLORS["text"])
        ax.set_ylabel(f"y ({ctx.unit_str})", color=LAYER_COLORS["text"])

    def pattern(self, theta, phi, ctx, r):
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        L_eff = r["L_eff"]
        return _patch_pattern(theta, phi, L_eff, r["W"], k0, ctx.h)


# ============================================================================
# Rectangular Rear-Fed (Coax Probe)
# ============================================================================

@register_antenna("Rectangular Patch — Rear-Fed (Coax Probe)", category="Patch")
class RectPatchRear(AntennaBase):
    notes = ("Coax pin through ground; x_feed measured from center (arcsin form). "
             "Teflon clearance hole in ground computed from coax dielectric εr.")
    polarization = "linear  (E along the L direction of the patch)"
    beam_axis = "broadside (+Z)"
    bandwidth_note = "narrowband (~2–5 %)"

    def inputs(self):
        return [
            Input("pin_dia", "SMA pin diameter (units)", "1.27"),
            Input("sma_er", "Coax dielectric εr", "2.08",
                  tooltip="PTFE ≈ 2.08"),
            Input("pin_ext", "Pin extension above patch (units)", "0.0"),
        ]

    def compute(self, ctx, params):
        dims = _patch_dimensions(ctx)
        W, L, Ereff = dims["W"], dims["L"], dims["Ereff"]
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        imp = _edge_resistance(L, W, k0)
        R_edge = imp["R_edge"]

        # Rear-fed uses arcsin from CENTER (matches user's MATLAB + Balanis)
        if ctx.z0 <= R_edge:
            x_feed = (L / np.pi) * np.arcsin(np.sqrt(ctx.z0 / R_edge))
        else:
            x_feed = L / 2

        pin_dia_m = ctx.m(params.get("pin_dia", "1.27"))
        sma_er = float(params.get("sma_er", "2.08"))
        pin_rad = pin_dia_m / 2

        # Size clearance hole so the coax section has target Z0
        sma_rad = coax.outer_from_inner(pin_rad, ctx.z0, sma_er)
        Z_coax = coax.impedance_from_diameters(pin_rad * 2, sma_rad * 2, sma_er)

        return {
            "W": W, "L": L, "Ereff": Ereff, "dL": dims["dL"],
            "R_edge": R_edge, "G1": imp["G1"], "G12": imp["G12"],
            "x_feed": x_feed, "pin_rad": pin_rad, "sma_rad": sma_rad,
            "Z_coax": Z_coax, "sma_er": sma_er,
            "L_eff": L + 2 * dims["dL"],
            "board_size": (L + 2 * ctx.Ls, W + 2 * ctx.Ws),
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Patch W           = {r['W']*m:.4f} {u}",
            f"  Patch L           = {r['L']*m:.4f} {u}",
            f"  ΔL (fringing)     = {r['dL']*m:.4f} {u}",
            f"  εr_eff            = {r['Ereff']:.3f}",
            f"  R_edge            = {r['R_edge']:.1f} Ω",
            f"  x_feed (from centre)= {r['x_feed']*m:.4f} {u}",
            f"  Coax pin radius   = {r['pin_rad']*m:.4f} {u}",
            f"  Teflon clearance r= {r['sma_rad']*m:.4f} {u}  (Z_coax={r['Z_coax']:.1f} Ω, εr={r['sma_er']:.2f})",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, W = r["L"] * m, r["W"] * m
        Ls, Ws = ctx.Ls * m, ctx.Ws * m
        xf = r["x_feed"] * m
        pr = r["pin_rad"] * m
        sr = r["sma_rad"] * m
        style_ax(ax.figure, ax, "Rectangular Patch (Rear-Fed Coax)", equal=True)

        ax.add_patch(mpatches.Rectangle(
            (-L/2 - Ls, -W/2 - Ws), L + 2*Ls, W + 2*Ws,
            facecolor=LAYER_COLORS["substrate"],
            edgecolor=LAYER_COLORS["axis"], lw=0.7, zorder=1))
        ax.add_patch(mpatches.Rectangle(
            (-L/2, -W/2), L, W, facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=2))

        # Clearance hole in ground (shown as dashed circle on ground layer)
        ax.add_patch(mpatches.Circle((xf, 0), sr, fill=False, ls="--",
                                     ec="white", lw=1.0, zorder=3))
        # PTFE plug
        ax.add_patch(mpatches.Circle((xf, 0), sr, facecolor="#dcdcdc",
                                     alpha=0.5, zorder=3))
        # Pin
        ax.add_patch(mpatches.Circle((xf, 0), pr,
                                     facecolor="#ff5050", edgecolor="black",
                                     lw=0.5, zorder=4))

        dim_horizontal(ax, -L/2, L/2, -W/2 - Ws*0.3, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -W/2, W/2, -L/2 - Ls*0.3, f"W = {W:.2f}", offset=0)
        # x_feed dim sits above the pin (clear of any callouts on the right)
        dim_horizontal(ax, 0, xf, W/2 - Ws*0.05,
                       f"x_feed = {xf:.2f}", offset=0,
                       color=LAYER_COLORS["dim_alt"])
        # Pin / Teflon callouts go to the RIGHT of the patch where there's
        # margin space, separated vertically so the two leaders don't collide.
        leader(ax, (xf + pr, 0), (L/2 + Ls*0.4, W*0.35),
               f"Pin Ø{2*pr:.3f}")
        leader(ax, (xf + sr*0.7, -sr*0.7),
               (L/2 + Ls*0.4, -W*0.35),
               f"Teflon Ø{2*sr:.3f}\nZ_coax={r['Z_coax']:.1f} Ω")

        # Overall board outline
        dim_board(ax, -L/2 - Ls, L/2 + Ls, -W/2 - Ws, W/2 + Ws,
                  pad_frac=0.12)

        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"], f"Substrate (εr={ctx.er:.2f})"),
            (LAYER_COLORS["copper"], "Top copper"),
            ("#ff5050", "Coax pin"),
            ("#dcdcdc", "PTFE / clearance"),
        ], loc="lower left")
        ax.margins(0.18)

    def plot_fields(self, ax, ctx, r):
        RectPatchInset.plot_fields(self, ax, ctx, r)

    def pattern(self, theta, phi, ctx, r):
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        return _patch_pattern(theta, phi, r["L_eff"], r["W"], k0, ctx.h)


# ============================================================================
# Rectangular Edge-Fed Stub-Tuned
# ============================================================================

@register_antenna("Rectangular Patch — Stub-Tuned (Edge-Fed)", category="Patch")
class RectPatchStub(AntennaBase):
    notes = "Shunt open-circuit stub at distance d from patch; no inset cuts."
    polarization = "linear  (E along the L direction of the patch)"
    beam_axis = "broadside (+Z)"
    bandwidth_note = "narrowband — stub gives single-frequency match"

    def inputs(self):
        return [
            Input("use_measured_ZA", "Use measured ZA?", "No",
                  choices=["No", "Yes"],
                  tooltip="If Yes, uses ZA_real + j·ZA_imag; otherwise uses the "
                          "cavity-model R_edge."),
            Input("ZA_real", "ZA real (Ω)", "475.22"),
            Input("ZA_imag", "ZA imag (Ω)", "8.74"),
        ]

    def compute(self, ctx, params):
        from calculators.matching import shunt_stub
        dims = _patch_dimensions(ctx)
        W, L, Ereff = dims["W"], dims["L"], dims["Ereff"]
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        imp = _edge_resistance(L, W, k0)

        # Accept "Yes"/"No" from dropdown, or legacy numeric "0"/"1" strings.
        raw_use = str(params.get("use_measured_ZA", "No")).strip().lower()
        use_meas = raw_use in ("yes", "1", "true", "on")
        if use_meas:
            ZA = complex(float(params.get("ZA_real", "475")),
                         float(params.get("ZA_imag", "0")))
        else:
            ZA = complex(imp["R_edge"], 0)

        # Microstrip feed line
        feed = microstrip.synthesize(ctx.z0, ctx.er, ctx.h)
        # Guided λ on the feed line
        lam_g = C_LIGHT / (ctx.fr * np.sqrt(feed["Ereff"]))

        sols = shunt_stub(ZA, ctx.z0, open_circuit=True)
        picks = []
        for s in sols:
            picks.append({
                "d": s["d_over_lambda"] * lam_g,
                "l": s["l_over_lambda"] * lam_g,
                "d_over_lambda": s["d_over_lambda"],
                "l_over_lambda": s["l_over_lambda"],
            })

        # Board outline matches plot_geometry: substrate extends from the
        # patch left edge past the stub junction (offset d on the first sol)
        # to a feed tail equal to max(Ls, 4·W_feed).
        d_first = picks[0]["d"] if picks else 0.0
        feed_tail = max(ctx.Ls, 4 * feed["W"])
        subs_w_m = L + 2 * ctx.Ls + d_first + feed_tail

        # Substrate runs from x = -L/2 - Ls to that + subs_w_m
        center_x = -L/2 - ctx.Ls + subs_w_m / 2
        return {
            "W": W, "L": L, "Ereff": Ereff, "dL": dims["dL"],
            "R_edge": imp["R_edge"], "ZA_used": ZA,
            "W_feed": feed["W"], "lam_g": lam_g,
            "stub_solutions": picks,
            "L_eff": L + 2 * dims["dL"],
            "board_size": (subs_w_m, W + 2 * ctx.Ws),
            "board_center_m": (center_x, 0.0),
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        out = [
            f"  Patch W        = {r['W']*m:.4f} {u}",
            f"  Patch L        = {r['L']*m:.4f} {u}",
            f"  R_edge         = {r['R_edge']:.1f} Ω",
            f"  ZA used        = {r['ZA_used'].real:.1f} + j{r['ZA_used'].imag:.1f} Ω",
            f"  Feed width     = {r['W_feed']*m:.4f} {u}",
            f"  λ_g (feed)     = {r['lam_g']*m:.4f} {u}",
            "",
            "  Stub matching solutions (open-circuit shunt stub, Z₀ feed):",
        ]
        for i, s in enumerate(r["stub_solutions"], 1):
            out.append(f"    [{i}] d = {s['d']*m:.3f} {u}  ({s['d_over_lambda']*360:.1f}°);"
                       f"  l_stub = {s['l']*m:.3f} {u}  ({s['l_over_lambda']*360:.1f}°)")
        return out

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, W = r["L"] * m, r["W"] * m
        Ls, Ws = ctx.Ls * m, ctx.Ws * m
        wf = r["W_feed"] * m
        d_m = r["stub_solutions"][0]["d"] * m if r["stub_solutions"] else 0
        l_m = r["stub_solutions"][0]["l"] * m if r["stub_solutions"] else 0

        style_ax(ax.figure, ax, "Patch — Stub-Tuned Feed", equal=True)
        # Substrate wide enough to host patch + stub arm + run to SMA.  We size it
        # so the feed reaches the substrate right edge.
        feed_tail = max(Ls, wf * 4)               # tail length after stub junction
        subs_w = L + 2*Ls + d_m + feed_tail
        ax.add_patch(mpatches.Rectangle(
            (-L/2 - Ls, -W/2 - Ws), subs_w, W + 2*Ws,
            facecolor=LAYER_COLORS["substrate"],
            edgecolor=LAYER_COLORS["axis"], lw=0.7, zorder=1))
        ax.add_patch(mpatches.Rectangle(
            (-L/2, -W/2), L, W, facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=2))
        # Feed line runs from patch edge to substrate right edge as one continuous trace
        feed_end = -L/2 - Ls + subs_w        # = L/2 + Ls + d_m + feed_tail
        ax.add_patch(mpatches.Rectangle(
            (L/2, -wf/2), feed_end - L/2, wf,
            facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=3))
        # Shunt stub branching upward at distance d
        ax.add_patch(mpatches.Rectangle(
            (L/2 + d_m - wf/2, wf/2), wf, l_m,
            facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=4))
        # SMA marker at the substrate edge
        ax.add_patch(mpatches.Circle((feed_end, 0), wf * 1.4,
                                     fill=False, ls=":", ec=LAYER_COLORS["copper_edge"],
                                     lw=0.9, zorder=5))
        dim_horizontal(ax, -L/2, L/2, -W/2 - Ws*0.3, f"L = {L:.2f}", offset=0)
        dim_vertical(ax, -W/2, W/2, -L/2 - Ls*0.3, f"W = {W:.2f}", offset=0)
        # 'd' annotation: dim line BELOW the substrate so it doesn't sit on
        # the feed line.
        dim_horizontal(ax, L/2, L/2 + d_m, -W/2 - Ws*0.55,
                       f"d = {d_m:.2f}", offset=0,
                       color=LAYER_COLORS["dim_alt"])
        # Stub length — labelled to the right of the stub strip
        dim_vertical(ax, wf/2, wf/2 + l_m, L/2 + d_m + wf*4.0,
                     f"l = {l_m:.2f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])

        # Overall board outline (board_size is in METERS; convert to display)
        bb_w_disp = r["board_size"][0] * m
        dim_board(ax, -L/2 - Ls, -L/2 - Ls + bb_w_disp,
                  -W/2 - Ws, W/2 + Ws, pad_frac=0.10)

        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"], "Substrate"),
            (LAYER_COLORS["copper"], "Top copper"),
        ], loc="lower left")
        ax.margins(0.14)

    def plot_fields(self, ax, ctx, r):
        RectPatchInset.plot_fields(self, ax, ctx, r)

    def pattern(self, theta, phi, ctx, r):
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        return _patch_pattern(theta, phi, r["L_eff"], r["W"], k0, ctx.h)


# ============================================================================
# Circular Patch (Rear-Fed)
# ============================================================================

@register_antenna("Circular Patch — Rear-Fed (Coax Probe)", category="Patch")
class CircularPatch(AntennaBase):
    notes = ("TM₁₁ mode, J′₁ root 1.8412. Feed at radius ρ tuned to match Z₀ via "
             "R_in(ρ) = R_edge·J₁²(kρ)/J₁²(ka).")
    polarization = "linear  (set by feed-pin azimuth — orthogonal pin gives CP pair)"
    beam_axis = "broadside (+Z)"
    bandwidth_note = "narrowband (~1–3 %)"

    def inputs(self):
        return [
            Input("pin_dia", "SMA pin diameter (units)", "1.27"),
            Input("sma_er", "Coax dielectric εr", "2.08"),
        ]

    def compute(self, ctx, params):
        er, h, fr = ctx.er, ctx.h, ctx.fr
        F = (1.8412 * C_LIGHT) / (2 * np.pi * fr * np.sqrt(er))
        # iterative fringing correction
        a = F / np.sqrt(1 + (2 * h / (np.pi * er * F)) *
                        (np.log(np.pi * F / (2 * h)) + 1.7726))
        # effective radius (slightly larger due to fringing)
        a_eff = a * np.sqrt(1 + (2 * h / (np.pi * er * a)) *
                            (np.log(np.pi * a / (2 * h)) + 1.7726))

        k0 = 2 * np.pi * fr / C_LIGHT
        # Edge resistance (cavity model, Balanis 14-76):
        # G_rad ≈ (k0·a)^2 / (480)  (approx); use numerical integration for better value
        def g_integrand(theta):
            # Balanis 14-67 — electric vector potential
            x = k0 * a_eff * np.sin(theta)
            J02 = special.jv(0, x) - special.jv(2, x)
            J02p = special.jv(0, x) + special.jv(2, x)
            return (J02 ** 2 * np.cos(theta) ** 2 +
                    J02p ** 2 * np.cos(theta) ** 2 * np.sin(theta) ** 2) * np.sin(theta)
        I, _ = integrate.quad(g_integrand, 0, np.pi / 2, limit=100)
        G_rad = (k0 * a_eff) ** 2 / (480) * (I)   # approximate
        # Fallback to simpler rule if integration is numerically small:
        if G_rad <= 0 or not np.isfinite(G_rad):
            G_rad = (k0 * a_eff) ** 2 / 480.0
        R_edge = 1.0 / (2 * G_rad)

        # Solve x_feed so R_in(x) = Z0: R(ρ) = R_edge · [J1(k·ρ)/J1(k·a)]²
        # where k = 1.8412/a (resonance), so we need ρ such that J1²(k·ρ) / J1²(k·a) = Z0/R_edge
        kc = 1.8412 / a_eff
        J1_a = special.jv(1, kc * a_eff)
        target = (ctx.z0 / R_edge) * J1_a ** 2
        from scipy.optimize import brentq
        try:
            rho = brentq(lambda r: special.jv(1, kc * r) ** 2 - target,
                         1e-6 * a_eff, a_eff - 1e-9)
        except ValueError:
            rho = 0.35 * a_eff
        pin_rad = ctx.m(params.get("pin_dia", "1.27")) / 2
        sma_er = float(params.get("sma_er", "2.08"))
        sma_rad = coax.outer_from_inner(pin_rad, ctx.z0, sma_er)
        # Patch edge as a parametric circle
        t_pts = np.linspace(0, 2*np.pi, 73)
        patch_pts = [(float(a * np.cos(t)), float(a * np.sin(t))) for t in t_pts]
        a_d = a * ctx.out_mult
        curves = [
            Curve(name="Circular patch edge",
                  equation="x(t)=a·cos(t),  y(t)=a·sin(t)",
                  parameters={"a": (a, "m  (patch radius)"),
                              "t": ((0.0, 2*np.pi), "rad")},
                  points_m=patch_pts, closed=True,
                  cst={
                      "x_t": f"{a_d:.6f}*cos(t)",
                      "y_t": f"{a_d:.6f}*sin(t)",
                      "z_t": "0",
                      "t_min": "0", "t_max": "2*pi", "t_unit": "rad",
                  }),
        ]
        return {
            "a": a, "a_eff": a_eff, "R_edge": R_edge,
            "x_feed": rho, "pin_rad": pin_rad, "sma_rad": sma_rad,
            "Ereff": er,   # circular patch doesn't define Ereff in the same way
            "Z_coax": coax.impedance_from_diameters(2*pin_rad, 2*sma_rad, sma_er),
            "board_size": (2 * a + 2 * ctx.Ls, 2 * a + 2 * ctx.Ws),
            "curves": curves,
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Patch radius a   = {r['a']*m:.4f} {u}",
            f"  Effective a_eff  = {r['a_eff']*m:.4f} {u}",
            f"  R_edge (ρ=a)     = {r['R_edge']:.1f} Ω",
            f"  Feed radial ρ    = {r['x_feed']*m:.4f} {u}",
            f"  Pin radius       = {r['pin_rad']*m:.4f} {u}",
            f"  Teflon outer r   = {r['sma_rad']*m:.4f} {u}",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        a, aeff = r["a"] * m, r["a_eff"] * m
        Ls, Ws = ctx.Ls * m, ctx.Ws * m
        xf = r["x_feed"] * m
        pr, sr = r["pin_rad"] * m, r["sma_rad"] * m
        style_ax(ax.figure, ax, "Circular Patch (Rear-Fed)", equal=True)
        ax.add_patch(mpatches.Rectangle(
            (-a - Ls, -a - Ws), 2*a + 2*Ls, 2*a + 2*Ws,
            facecolor=LAYER_COLORS["substrate"], edgecolor=LAYER_COLORS["axis"],
            lw=0.7, zorder=1))
        ax.add_patch(mpatches.Circle((0, 0), a, facecolor=LAYER_COLORS["copper"],
                                     edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=2))
        # Show effective-radius ring (dashed)
        ax.add_patch(mpatches.Circle((0, 0), aeff, fill=False, ec="cyan",
                                     ls="--", lw=0.7, zorder=3))
        ax.add_patch(mpatches.Circle((xf, 0), sr, fill=False, ls="--",
                                     ec="white", zorder=3))
        ax.add_patch(mpatches.Circle((xf, 0), sr, facecolor="#dcdcdc", alpha=0.5, zorder=3))
        ax.add_patch(mpatches.Circle((xf, 0), pr, facecolor="#ff5050",
                                     edgecolor="black", lw=0.5, zorder=4))
        dim_radial(ax, (0, 0), a, 45, f"a = {a:.2f}")
        # ρ dim — keep it inside the patch on a free quadrant (below feed)
        dim_horizontal(ax, 0, xf, -a*0.55, f"ρ = {xf:.2f}", offset=0,
                       color=LAYER_COLORS["dim_alt"])
        # Coax / Teflon callout: parked outside the patch, to the right, so
        # the leader doesn't run across the patch face.
        leader(ax, (xf + sr*0.7, -sr*0.7),
               (a + Ls*0.5, -a*0.6),
               f"Pin Ø{2*pr:.3f}\nTef. Ø{2*sr:.3f}\nZ_coax={r['Z_coax']:.1f} Ω")

        # Overall board outline
        dim_board(ax, -a - Ls, a + Ls, -a - Ws, a + Ws, pad_frac=0.10)

        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"], "Substrate"),
            (LAYER_COLORS["copper"], "Patch copper"),
            ("#ff5050", "Coax pin"),
        ], loc="lower left")
        ax.margins(0.18)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "TM₁₁ Mode |Ez|  (with Jρ arrows)", equal=True, grid=False)
        a = r["a"] * ctx.out_mult
        X, Y = np.meshgrid(np.linspace(-a, a, 200),
                           np.linspace(-a, a, 200))
        R = np.hypot(X, Y)
        Phi = np.arctan2(Y, X)
        kc = 1.8412 / a
        Ez = special.jv(1, kc * R) * np.cos(Phi)
        Ez[R > a] = np.nan
        im = ax.contourf(X, Y, np.abs(Ez), 60, cmap="magma")
        # Quiver of in-plane surface currents (rough: J ⊥ grad Ez)
        rs = np.linspace(a * 0.15, a * 0.85, 6)
        phs = np.linspace(0, 2*np.pi, 14, endpoint=False)
        R2, P2 = np.meshgrid(rs, phs)
        Xq = R2 * np.cos(P2); Yq = R2 * np.sin(P2)
        # rough current: Jr ∝ ∂Ez/∂ρ, Jφ ∝ (1/ρ)·∂Ez/∂φ
        Jr = kc * (special.jv(0, kc * R2) - special.jv(2, kc * R2))/2 * np.cos(P2)
        Jp = -special.jv(1, kc * R2) / R2 * np.sin(P2)
        Jx = Jr * np.cos(P2) - Jp * np.sin(P2)
        Jy = Jr * np.sin(P2) + Jp * np.cos(P2)
        ax.quiver(Xq, Yq, Jx, Jy, color="cyan", pivot="mid", scale=30,
                  alpha=0.85, width=0.004)
        ax.add_patch(mpatches.Circle((0, 0), a, fill=False, ec="white", lw=1.2))
        cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=LAYER_COLORS["text"])
        cb.set_label("Normalized |Ez|", color=LAYER_COLORS["text"])
        ax.set_xlabel(f"x ({ctx.unit_str})", color=LAYER_COLORS["text"])
        ax.set_ylabel(f"y ({ctx.unit_str})", color=LAYER_COLORS["text"])

    def pattern(self, theta, phi, ctx, r):
        # Balanis 14-79a – 14-79b (simplified)
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        a = r["a_eff"]
        x = k0 * a * np.sin(theta)
        # avoid division by zero
        safe = np.where(np.abs(x) < 1e-9, 1e-9, x)
        J02 = special.jv(0, safe) - special.jv(2, safe)
        # cos(φ) E-plane dependency (arbitrary polarization choice)
        F = np.abs(J02 * np.cos(phi))
        # Element pattern above ground plane
        above = np.where(np.cos(theta) > 0, np.cos(theta), 0)
        return F * above


# ============================================================================
# PIFA (Planar Inverted-F)
# ============================================================================

@register_antenna("PIFA — Planar Inverted-F", category="Patch")
class PIFA(AntennaBase):
    notes = "L + W ≈ λg/4; shorting pin at patch edge, feed pin nearby."
    polarization = "linear  (E parallel to the shorted edge)"
    beam_axis = "broadside (+Z), with some +X tilt due to short"
    bandwidth_note = "narrowband (~5 %, BW grows with substrate height)"

    def inputs(self):
        return [
            Input("W_target", "Target patch width (units)", "8.0"),
            Input("short_w", "Shorting wall width (units)", "2.0"),
            Input("feed_offset", "Feed offset from short (units)", "1.0"),
        ]

    def compute(self, ctx, params):
        # Effective εr for a half-filled / quasi-TEM cavity (Soras et al.)
        er_eff = (ctx.er + 1) / 2
        W_target = ctx.m(params.get("W_target", "8.0"))
        total = C_LIGHT / (4 * ctx.fr * np.sqrt(er_eff))
        if W_target >= total * 0.9:
            W_target = total * 0.4
        L = total - W_target
        short_w  = ctx.m(params.get("short_w", "2.0"))
        feed_off = ctx.m(params.get("feed_offset", "1.0"))
        return {"L": L, "W": W_target, "Ereff": er_eff,
                "short_w": short_w, "feed_off": feed_off, "total": total,
                "board_size": (L + 2 * ctx.Ls, W_target + 2 * ctx.Ws),
                # PIFA substrate spans x=[-Ls, L+Ls] so the centre sits at L/2
                "board_center_m": (L / 2, 0.0)}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Patch L       = {r['L']*m:.3f} {u}",
            f"  Patch W       = {r['W']*m:.3f} {u}",
            f"  L + W         = {(r['L']+r['W'])*m:.3f} {u}  (≈ λg/4 = {r['total']*m:.3f})",
            f"  Short wall w  = {r['short_w']*m:.3f} {u}",
            f"  Feed offset   = {r['feed_off']*m:.3f} {u}",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, W = r["L"] * m, r["W"] * m
        sw = r["short_w"] * m
        fo = r["feed_off"] * m
        Ls, Ws = ctx.Ls * m, ctx.Ws * m
        style_ax(ax.figure, ax, "PIFA — Top view (patch + shorting wall)",
                 equal=True)

        # Substrate board outline
        ax.add_patch(mpatches.Rectangle(
            (-Ls, -W/2 - Ws), L + 2*Ls, W + 2*Ws,
            facecolor=LAYER_COLORS["substrate"],
            edgecolor=LAYER_COLORS["axis"], lw=0.7, zorder=1))
        # Patch (top copper) at x ∈ [0, L]
        ax.add_patch(mpatches.Rectangle(
            (0, -W/2), L, W, facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=2))
        # Shorting wall — vertical strip running off the patch's left edge, width=sw.
        # Drawn as a thick stripe with hatch so it reads as a through-via/wall.
        wall_thk = max(L * 0.08, 0.4)         # ≥ 0.4 mm stripe so it's visible
        ax.add_patch(mpatches.Rectangle(
            (-wall_thk, -sw/2), wall_thk, sw,
            facecolor="#bdbdbd", edgecolor="#4a4a4a",
            lw=0.8, hatch="////", zorder=4))
        # Tie the wall visually down to the ground (dashed outline of copper via)
        ax.plot([-wall_thk/2, -wall_thk/2],
                [sw/2, -W/2 - Ws*0.5], ls=":", color="#7a7a7a", lw=0.9, zorder=3)
        ax.plot([-wall_thk/2, -wall_thk/2],
                [-sw/2, -W/2 - Ws*0.5], ls=":", color="#7a7a7a", lw=0.9, zorder=3)
        # Feed pin
        pin_r = max(L * 0.035, 0.25)
        ax.add_patch(mpatches.Circle((fo, 0), pin_r, facecolor="#ff5050",
                                     edgecolor="black", lw=0.6, zorder=5))
        # Ground indication: text on bottom margin saying "Ground plane (bottom layer)"
        ax.text(L/2, -W/2 - Ws*0.7, "⇣ Ground plane on bottom (full copper)",
                ha="center", va="center", color="#c0c0c0", fontsize=8,
                style="italic", zorder=6)

        # Dimensions — the patch is small, so park every label OUTSIDE the
        # copper to keep things readable.
        dim_horizontal(ax, 0, L, W/2 + Ws*0.4, f"L = {L:.2f}", offset=0)
        dim_vertical(ax,  -W/2, W/2, L + Ls*0.25, f"W = {W:.2f}", offset=0)
        dim_vertical(ax,  -sw/2, sw/2, -wall_thk - Ls*0.25,
                     f"short = {sw:.2f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        # 'feed' dim below the patch
        leader(ax, (fo, 0), (fo + Ls*0.5, -W/2 - Ws*0.2),
               f"feed = {fo:.2f}", color=LAYER_COLORS["dim_alt"])
        leader(ax, (fo, 0), (-Ls*0.5, -W/2 - Ws*0.5),
               f"Feed pin Ø{2*pin_r:.2f}")

        # Overall board outline (substrate envelope)
        dim_board(ax, -Ls, L + Ls, -W/2 - Ws, W/2 + Ws, pad_frac=0.10)

        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"],  f"Substrate (εr={ctx.er:.2f}, h={ctx.h*m:.2f})"),
            (LAYER_COLORS["copper"],     "Top patch (L × W)"),
            ("#bdbdbd",                  "Shorting wall (patch→GND)"),
            ("#ff5050",                  "Feed pin (coax from GND)"),
        ], loc="lower right")
        ax.margins(0.22)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "PIFA Quarter-wave E-field", equal=True, grid=False)
        L, W = r["L"] * ctx.out_mult, r["W"] * ctx.out_mult
        X, Y = np.meshgrid(np.linspace(0, L, 200), np.linspace(-W/2, W/2, 140))
        # Short at x=0 (null), open at x=L (max) → sin(πx/2L)
        Ez = np.abs(np.sin(np.pi * X / (2 * L)))
        im = ax.contourf(X, Y, Ez, 60, cmap="magma")
        ax.plot([0, L, L, 0, 0], [-W/2, -W/2, W/2, W/2, -W/2], "w-", lw=1.2)
        cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=LAYER_COLORS["text"])
        cb.set_label("|Ez|", color=LAYER_COLORS["text"])

    def pattern(self, theta, phi, ctx, r):
        # Quarter-wave patch pattern: similar to half patch
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        L, W = r["L"], r["W"]
        X = 0.5 * k0 * W * np.sin(theta) * np.sin(phi)
        Y = k0 * L * np.sin(theta) * np.cos(phi)
        sinc_x = np.where(np.abs(X) < 1e-9, 1.0, np.sin(X) / np.where(X == 0, 1, X))
        element = np.abs(sinc_x * np.sin(Y / 2))
        above = np.where(np.cos(theta) > 0, np.cos(theta), 0)
        return element * above


# ============================================================================
# 2x1 Corporate-fed Array
# ============================================================================

@register_antenna("Patch Array 2×1 (Corporate-Fed)", category="Patch")
class Array2x1(AntennaBase):
    notes = "Two rectangular patches fed via T-junction with λ/4 impedance matching."
    polarization = "linear  (E along the patch L direction)"
    beam_axis = "broadside (+Z), narrower in H-plane than single patch"
    bandwidth_note = "narrowband — element BW dominates, ~2–5 %"

    def inputs(self):
        return [Input("spacing_lambda", "Element spacing (λ₀)", "0.5")]

    def compute(self, ctx, params):
        dims = _patch_dimensions(ctx)
        W, L = dims["W"], dims["L"]
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        imp = _edge_resistance(L, W, k0)
        spacing = float(params.get("spacing_lambda", "0.5")) * ctx.lambda0
        feed = microstrip.synthesize(ctx.z0, ctx.er, ctx.h)
        # Quarter-wave transformer between paralleled 100Ω pair (2x50Ω) and 50Ω source:
        # With each patch edge ≈ R_edge, we want to transform R_edge → 2·Z0 so two in
        # parallel give Z0; transformer impedance = √(R_edge · 2·Z0).
        z_trans = np.sqrt(imp["R_edge"] * 2 * ctx.z0)
        qw = microstrip.synthesize(z_trans, ctx.er, ctx.h)
        lam_g_feed = C_LIGHT / (ctx.fr * np.sqrt(qw["Ereff"]))
        # Board outline mirrors the corporate-feed layout in plot_geometry.
        qw_len = lam_g_feed / 4
        feed_tail = max(ctx.Ls, 1.2 * qw_len)
        board_w_m = spacing + L + 2 * ctx.Ls
        board_h_m = W + ctx.Ws + qw_len + feed["W"] + feed_tail

        # Substrate y range: from board_bot = -qw_len - feed["W"] - feed_tail
        #                    up to board_top = W + ctx.Ws.
        board_bot = -qw_len - feed["W"] - feed_tail
        board_top = W + ctx.Ws
        return {
            "W": W, "L": L, "Ereff": dims["Ereff"],
            "R_edge": imp["R_edge"], "spacing": spacing,
            "W_feed": feed["W"], "W_qw": qw["W"], "Z_qw": z_trans,
            "qw_len": qw_len,
            "L_eff": L + 2 * dims["dL"],
            "board_size": (board_w_m, board_h_m),
            "board_center_m": (0.0, (board_top + board_bot) / 2),
        }

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        return [
            f"  Element W       = {r['W']*m:.4f} {u}",
            f"  Element L       = {r['L']*m:.4f} {u}",
            f"  Spacing         = {r['spacing']*m:.4f} {u}",
            f"  Feed line W     = {r['W_feed']*m:.4f} {u}",
            f"  λ/4 transformer = {r['W_qw']*m:.4f} {u} wide, "
            f"{r['qw_len']*m:.4f} {u} long  (Z={r['Z_qw']:.1f} Ω)",
        ]

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        L, W   = r["L"] * m, r["W"] * m
        S      = r["spacing"] * m
        wf     = r["W_feed"] * m
        wqw    = r["W_qw"] * m
        qwL    = r["qw_len"] * m
        Ls, Ws = ctx.Ls * m, ctx.Ws * m
        style_ax(ax.figure, ax, "2×1 Patch Array (Corporate Feed)", equal=True)

        # Layout (corporate T-feed):
        #   patches sit at the TOP of the board (their bottom edge at y = 0)
        #   each patch has a λ/4 transformer running from y=0 down to y=-qwL
        #   horizontal combining line at y ≈ -qwL
        #   main feed trace goes straight down from (0, -qwL) to substrate bottom edge
        patch_bot  = 0.0
        patch_top  = patch_bot + W
        qw_bot     = -qwL                     # bottom of λ/4 transformer
        tjunc_y    = qw_bot                   # T-junction centerline
        feed_tail  = max(Ls, 1.2 * qwL)       # run from T-junction to board edge
        board_bot  = tjunc_y - wf - feed_tail
        board_top  = patch_top + Ws
        board_xmin = -S/2 - L/2 - Ls
        board_xmax =  S/2 + L/2 + Ls

        ax.add_patch(mpatches.Rectangle(
            (board_xmin, board_bot), board_xmax - board_xmin, board_top - board_bot,
            facecolor=LAYER_COLORS["substrate"],
            edgecolor=LAYER_COLORS["axis"], lw=0.7, zorder=1))

        for sign in (-1, +1):
            # Element patch
            ax.add_patch(mpatches.Rectangle(
                (sign*S/2 - L/2, patch_bot), L, W,
                facecolor=LAYER_COLORS["copper"],
                edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=2))
            # λ/4 transformer stub between patch edge (y=0) and T-junction
            ax.add_patch(mpatches.Rectangle(
                (sign*S/2 - wqw/2, qw_bot), wqw, qwL,
                facecolor=LAYER_COLORS["copper"],
                edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=3))

        # Horizontal T-combiner
        ax.add_patch(mpatches.Rectangle(
            (-S/2 - wqw/2, tjunc_y - wf/2), S + wqw, wf,
            facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=3))
        # Main feed line runs to substrate bottom edge
        ax.add_patch(mpatches.Rectangle(
            (-wf/2, board_bot), wf, tjunc_y - wf/2 - board_bot,
            facecolor=LAYER_COLORS["copper"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=0.8, zorder=3))
        # SMA footprint at bottom edge
        ax.add_patch(mpatches.Circle((0, board_bot), wf * 1.4,
                                     fill=False, ls=":",
                                     ec=LAYER_COLORS["copper_edge"], lw=0.9,
                                     zorder=5))

        # Dimensions
        dim_horizontal(ax, -S/2, S/2, patch_top + Ws * 0.45,
                       f"S = {S:.2f}", offset=0)
        dim_vertical(ax, patch_bot, patch_top, -S/2 - L/2 - Ls*0.4,
                     f"W = {W:.2f}", offset=0, color=LAYER_COLORS["dim_alt"])
        dim_horizontal(ax, -S/2 - L/2, -S/2 + L/2, patch_top + Ws*0.1,
                       f"L = {L:.2f}", offset=0,
                       color=LAYER_COLORS["dim_alt"])
        dim_vertical(ax, qw_bot, patch_bot, S/2 + L/2 + Ls*0.4,
                     f"λ/4 = {qwL:.2f}", offset=0,
                     color=LAYER_COLORS["dim_alt"])
        leader(ax, (0, board_bot + feed_tail*0.3),
               (S/4, board_bot + feed_tail*0.05),
               f"Feed (Z₀={ctx.z0:.0f} Ω)")

        # Overall board outline (envelope of the substrate)
        dim_board(ax, board_xmin, board_xmax, board_bot, board_top,
                  pad_frac=0.10)

        add_layer_legend(ax, [
            (LAYER_COLORS["substrate"], "Substrate"),
            (LAYER_COLORS["copper"],    "Top copper (patches + feed)"),
        ], loc="lower right")
        ax.margins(0.14)

    def plot_fields(self, ax, ctx, r):
        style_ax(ax.figure, ax, "Array Elements — TM₁₀ |Ez|", equal=True, grid=False)
        L, W = r["L"] * ctx.out_mult, r["W"] * ctx.out_mult
        S = r["spacing"] * ctx.out_mult
        X, Y = np.meshgrid(np.linspace(-S - L, S + L, 250),
                           np.linspace(-W, W, 150))
        Ez = np.zeros_like(X)
        for sign in (-1, +1):
            mask = (np.abs(X - sign*S/2) <= L/2) & (np.abs(Y) <= W/2)
            Ez[mask] = np.abs(np.cos(np.pi * ((X[mask] - sign*S/2) + L/2) / L))
        im = ax.contourf(X, Y, Ez, 60, cmap="magma")
        cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=LAYER_COLORS["text"])

    def pattern(self, theta, phi, ctx, r):
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        # Element: rectangular patch
        elem = _patch_pattern(theta, phi, r["L_eff"], r["W"], k0, ctx.h)
        # 2-element array along x, spacing S
        AF = 2 * np.cos(k0 * r["spacing"] / 2 * np.sin(theta) * np.cos(phi))
        return np.abs(elem * AF)
