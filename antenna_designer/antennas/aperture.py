"""
Aperture antennas — rectangular slot, bowtie, Vivaldi, pyramidal horn.
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches
from matplotlib.path import Path as MPath

from .base import AntennaBase, Context, Input, Curve, register_antenna, C_LIGHT, ETA0
from calculators import microstrip
from plotting.cad import (
    LAYER_COLORS, style_ax, dim_horizontal, dim_vertical, dim_linear,
    angle_dim, leader, add_layer_legend, dim_board,
)


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

        cavity_dia = ctx.m_or(params.get("cavity_dia"),
                              lam_g_slot_at_fL / 3)
        stub_ratio = float(params.get("stub_ratio", "0.25"))
        stub_angle = float(params.get("stub_angle", "45"))
        stub_len   = stub_ratio * lam_g_strip
        feed_Z     = float(params.get("feed_Z", "50"))
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
        if feed_side == "left":
            y_run    = 0.55 * (board_wid / 2)
            feed_len = (feed_cross_x - cav_left + m_back) + y_run
        else:
            feed_len = board_wid / 2

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
                    "x_t":  "t",
                    "y_t":  "min((w0/2)*exp(R*t), W_ap/2)",
                    "z_t":  "0",
                    "t_min": "0",
                    "t_max": "L",
                    "t_unit": ctx.unit_str,
                },
                dxf_combined=False,
            ),
            Curve(
                name="Lower taper edge (mirror of upper)",
                equation="y_lower(x) = −(w0/2) · exp(R · x),  clipped to −W_ap/2",
                parameters={
                    "w0":   (w0,   "m"),
                    "R":    (R,    "1/m"),
                    "W_ap": (W_ap, "m"),
                    "x":    ((0.0, L), "m"),
                },
                points_m=[(float(x), float(-y)) for x, y in zip(xs, y_upper)],
                cst={
                    "x_t":  "t",
                    "y_t":  "-min((w0/2)*exp(R*t), W_ap/2)",
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
                    "x_t":  "L",
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
                equation=("(x − cav_cx)² + y² = cav_r²,  arc from (0,−w0/2) "
                          "around the back to (0,+w0/2)"),
                parameters={
                    "cav_cx": (cav_cx, "m"),
                    "cav_r":  (cav_r,  "m"),
                    "a0":     (a0,     "rad"),
                },
                points_m=cav_back_pts,
                cst={
                    "x_t":  "cav_cx + cav_r*cos(t)",
                    "y_t":  "cav_r*sin(t)",
                    "z_t":  "0",
                    "t_min": "a0",
                    "t_max": "2*pi - a0",
                    "t_unit": "rad",
                },
                note=("Component of the closed slot+cavity boundary. "
                      "Goes CCW from a0 to 2π−a0 along the back of the "
                      "cavity (away from the slot)."),
                dxf_combined=False,
            ),
            Curve(
                name="Back-cavity circle (full, for reference)",
                equation="(x − cav_cx)² + y² = cav_r²",
                parameters={
                    "cav_cx": (cav_cx, "m"),
                    "cav_r":  (cav_r,  "m"),
                },
                points_m=cav_pts,
                closed=True,
                cst={
                    "x_t":  "cav_cx + cav_r*cos(t)",
                    "y_t":  "cav_r*sin(t)",
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
                "cav_r":  (cav_r,  "m"),
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
                 "y(x) = ±(w0/2) · exp(R · x),   clipped to ±W_ap/2"),
                ("Taper rate",
                 "R = ln(W_ap / w0) / L"),
                ("Back-cavity circle",
                 "(x − cav_cx)² + y² = cav_r²"),
                ("Cavity centre (so the cavity passes through (0, ±w0/2))",
                 "cav_cx = −√(cav_r² − (w0/2)²)"),
                ("Cavity-throat angle",
                 "a0 = arcsin(w0 / (2·cav_r))"),
                ("Microstrip-to-slotline crossing (λ/4 of slotline at fr)",
                 "x_cross = λ_g_slot / 4  with  λ_g_slot = c / (fr·√((εr+1)/2))"),
            ],
            "cst_parameters": {
                # --- base (user-tunable) ---
                "L":      {"value": L * mu,           "unit": ctx.unit_str,
                           "comment": "Taper length"},
                "W_ap":   {"value": W_ap * mu,        "unit": ctx.unit_str,
                           "comment": "Aperture (mouth) width"},
                "w0":     {"value": w0 * mu,          "unit": ctx.unit_str,
                           "comment": "Throat (slotline) width"},
                "R":      {"value": R / mu,           "unit": f"1/{ctx.unit_str}",
                           "comment": "Exponential taper rate"},
                "cav_r":  {"value": cav_r * mu,       "unit": ctx.unit_str,
                           "comment": "Back-cavity radius"},
                "h":      {"value": ctx.h * mu,       "unit": ctx.unit_str,
                           "comment": "Substrate thickness"},
                "er":     {"value": ctx.er,           "unit": "",
                           "comment": "Substrate relative permittivity"},
                "W_feed": {"value": feed["W"] * mu,   "unit": ctx.unit_str,
                           "comment": "Microstrip feed width (Z0 = "
                                      f"{feed_Z:.0f} Ω)"},
                "m_back": {"value": m_back * mu,      "unit": ctx.unit_str,
                           "comment": "Substrate margin behind cavity"},
                "m_side": {"value": m_side * mu,      "unit": ctx.unit_str,
                           "comment": "Substrate margin beside taper"},
                # --- derived (formulas, plus the value the formula evaluates
                #     to so the user can sanity-check after pasting) ---
                "cav_cx": {"formula": "-sqrt(cav_r^2 - (w0/2)^2)",
                           "value":  cav_cx * mu,
                           "unit":   ctx.unit_str,
                           "comment": "Cavity centre x"},
                "a0":     {"formula": "asin(w0/(2*cav_r))",
                           "value":  a0,
                           "unit":   "rad",
                           "comment": "Cavity-throat angle"},
                "board_L":{"formula": "L - (cav_cx - cav_r) + m_back",
                           "value":  board_len * mu,
                           "unit":   ctx.unit_str,
                           "comment": "Total board length"},
                "board_W":{"formula": "W_ap + 2*m_side",
                           "value":  board_wid * mu,
                           "unit":   ctx.unit_str,
                           "comment": "Total board width"},
            },
            "cst_recipe_steps": [
                "1) Build the ground-plane copper rectangle of size "
                "board_L × board_W centred on the origin (or wherever).",
                "2) Build all five analytical curves above.",
                "3) Curves ▸ Join Curves: upper_taper → aperture_right_edge "
                "→ lower_taper (reversed) → cavity_arc.  This makes one "
                "closed loop.",
                "4) Curves ▸ Cover Curve on that loop → one face.",
                "5) Boolean ▸ Subtract that face from the ground-plane "
                "copper.  Done.",
                "   (Now you can sweep L, W_ap, w0, R, cav_r, … and CST "
                "re-meshes automatically.)",
            ],
        }

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
