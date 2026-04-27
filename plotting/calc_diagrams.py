"""
Small labelled cross-section diagrams for the Calculators tab.

Each `draw_*` function takes a matplotlib Axes and renders a schematic with
variable-name labels matching the calculator's input fields. These are
qualitative sketches (unitless), intended to answer "which input is which."
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches
from matplotlib.patches import FancyArrowPatch
from .cad import LAYER_COLORS


def _style(ax, title: str):
    ax.set_facecolor(LAYER_COLORS["bg"])
    ax.figure.patch.set_facecolor(LAYER_COLORS["panel_bg"])
    ax.set_title(title, color=LAYER_COLORS["text"], fontsize=10, pad=6)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_aspect("equal", adjustable="box")
    ax.margins(0)


def _dim_h(ax, x0, x1, y, label, color=None):
    color = color or LAYER_COLORS["dim"]
    ax.annotate("", xy=(x1, y), xytext=(x0, y),
                arrowprops=dict(arrowstyle="<|-|>",
                                 color=color, lw=1.0,
                                 mutation_scale=8))
    ax.text((x0 + x1) / 2, y + 0.02, label, color=color,
            ha="center", va="bottom", fontsize=9)


def _dim_v(ax, y0, y1, x, label, color=None):
    color = color or LAYER_COLORS["dim"]
    ax.annotate("", xy=(x, y1), xytext=(x, y0),
                arrowprops=dict(arrowstyle="<|-|>",
                                 color=color, lw=1.0,
                                 mutation_scale=8))
    ax.text(x + 0.02, (y0 + y1) / 2, label, color=color,
            ha="left", va="center", fontsize=9)


# ----------------------------------------------------------------------
# Microstrip
# ----------------------------------------------------------------------
def draw_microstrip(ax):
    _style(ax, "Microstrip — cross-section")
    # Substrate
    ax.add_patch(mpatches.Rectangle((0, 0.15), 2.4, 0.35,
                 facecolor=LAYER_COLORS["substrate"], zorder=1))
    # Ground plane (thin strip on bottom)
    ax.add_patch(mpatches.Rectangle((0, 0.08), 2.4, 0.07,
                 facecolor=LAYER_COLORS["copper"],
                 edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=2))
    # Top signal trace (width W)
    ax.add_patch(mpatches.Rectangle((0.80, 0.50), 0.8, 0.08,
                 facecolor=LAYER_COLORS["copper"],
                 edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=3))
    # E-field curved lines from signal to ground (suggestive only)
    for x0 in (0.90, 1.10, 1.30, 1.50):
        theta = np.linspace(np.pi, 2*np.pi, 20)
        r = 0.18
        cx = x0
        cy = 0.50
        ax.plot(cx + r*np.cos(theta),
                cy + r*np.sin(theta),
                color=LAYER_COLORS["dim_special"], lw=0.6, alpha=0.55)

    # Labels
    _dim_h(ax, 0.80, 1.60, 0.68, "W")
    _dim_v(ax, 0.15, 0.50, 1.72, "h",
           color=LAYER_COLORS["dim_alt"])
    ax.text(0.02, 0.12, "GND", color=LAYER_COLORS["text"],
            fontsize=8, va="center")
    ax.text(0.02, 0.33, f"εr", color=LAYER_COLORS["text"],
            fontsize=9, va="center", style="italic")
    ax.text(1.20, 0.56, "signal", color=LAYER_COLORS["text"],
            fontsize=7, ha="center", va="bottom")

    ax.set_xlim(-0.05, 2.45)
    ax.set_ylim(-0.05, 0.90)


# ----------------------------------------------------------------------
# CPW / GCPW
# ----------------------------------------------------------------------
def draw_cpw(ax, grounded: bool = False):
    _style(ax, "CPW" + (" with ground (GCPW)" if grounded else "") +
              " — cross-section")
    # Substrate
    ax.add_patch(mpatches.Rectangle((0, 0.15), 2.4, 0.40,
                 facecolor=LAYER_COLORS["substrate"], zorder=1))
    # Optional bottom ground
    if grounded:
        ax.add_patch(mpatches.Rectangle((0, 0.08), 2.4, 0.07,
                     facecolor=LAYER_COLORS["copper"],
                     edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=2))
    # Top metal: ground | gap | signal | gap | ground
    s_x0, s_x1 = 1.00, 1.40        # signal
    gap = 0.15
    g_left_x0, g_left_x1 = 0.10, s_x0 - gap
    g_right_x0, g_right_x1 = s_x1 + gap, 2.30
    top_y, top_h = 0.55, 0.08
    for (x0, x1, lbl) in [(g_left_x0, g_left_x1, "GND"),
                          (s_x0, s_x1, "s"),
                          (g_right_x0, g_right_x1, "GND")]:
        ax.add_patch(mpatches.Rectangle((x0, top_y), x1 - x0, top_h,
                     facecolor=LAYER_COLORS["copper"],
                     edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=3))
    # Label ground and signal
    ax.text((g_left_x0+g_left_x1)/2, top_y + top_h/2, "GND",
            ha="center", va="center", fontsize=8, color="black")
    ax.text((g_right_x0+g_right_x1)/2, top_y + top_h/2, "GND",
            ha="center", va="center", fontsize=8, color="black")
    ax.text((s_x0+s_x1)/2, top_y + top_h + 0.03, "signal",
            ha="center", va="bottom", fontsize=7,
            color=LAYER_COLORS["text"])

    # Dimensions
    _dim_h(ax, s_x0, s_x1, top_y + top_h + 0.12, "s")
    _dim_h(ax, g_left_x1, s_x0, top_y - 0.08, "w",
           color=LAYER_COLORS["dim_alt"])
    _dim_h(ax, s_x1, g_right_x0, top_y - 0.08, "w",
           color=LAYER_COLORS["dim_alt"])
    _dim_v(ax, 0.15, top_y, 2.45, "h",
           color=LAYER_COLORS["dim_alt"])
    ax.text(0.02, 0.34, "εr", color=LAYER_COLORS["text"],
            fontsize=9, va="center", style="italic")
    if grounded:
        ax.text(0.02, 0.11, "GND", color=LAYER_COLORS["text"],
                fontsize=8, va="center")

    ax.set_xlim(-0.05, 2.60)
    ax.set_ylim(-0.05, 0.90)


# ----------------------------------------------------------------------
# Coaxial
# ----------------------------------------------------------------------
def draw_coax(ax):
    _style(ax, "Coaxial line — end-on section")
    # Outer conductor (dark ring), dielectric (bronze), inner conductor
    R_outer_outer = 0.48
    R_outer_inner = 0.42
    R_inner = 0.08
    # Outer conductor as annulus: draw big circle then erase inner with outer_inner
    ax.add_patch(mpatches.Circle((0, 0), R_outer_outer,
                 facecolor=LAYER_COLORS["ground"],
                 edgecolor=LAYER_COLORS["axis"], lw=0.6, zorder=1))
    ax.add_patch(mpatches.Circle((0, 0), R_outer_inner,
                 facecolor=LAYER_COLORS["dielectric"],
                 edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=2))
    ax.add_patch(mpatches.Circle((0, 0), R_inner,
                 facecolor=LAYER_COLORS["copper"],
                 edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=3))

    # Diameter dimensions (inner and outer)
    ax.annotate("", xy=(R_inner, 0), xytext=(-R_inner, 0),
                arrowprops=dict(arrowstyle="<|-|>",
                                 color=LAYER_COLORS["dim"], lw=1.0,
                                 mutation_scale=8))
    ax.text(0, R_inner + 0.03, "d",
            ha="center", va="bottom", color=LAYER_COLORS["dim"], fontsize=10)
    ax.annotate("", xy=(R_outer_inner, -0.08), xytext=(-R_outer_inner, -0.08),
                arrowprops=dict(arrowstyle="<|-|>",
                                 color=LAYER_COLORS["dim_alt"], lw=1.0,
                                 mutation_scale=8))
    ax.text(0, -0.17, "D",
            ha="center", va="top", color=LAYER_COLORS["dim_alt"], fontsize=10)

    # Labels
    ax.text(R_outer_inner + 0.05, R_outer_inner + 0.05, "outer GND",
            color=LAYER_COLORS["text"], fontsize=8)
    ax.text(0.14, 0.30, "εr", color=LAYER_COLORS["text"],
            fontsize=9, style="italic")
    ax.text(0, 0, "", ha="center", va="center")  # center marker not needed

    ax.set_xlim(-0.65, 0.70)
    ax.set_ylim(-0.60, 0.60)


# ----------------------------------------------------------------------
# Stripline
# ----------------------------------------------------------------------
def draw_stripline(ax):
    _style(ax, "Stripline — cross-section")
    # Two ground planes, dielectric between, centered strip
    ax.add_patch(mpatches.Rectangle((0, 0.80), 2.4, 0.10,
                 facecolor=LAYER_COLORS["copper"],
                 edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=3))
    ax.add_patch(mpatches.Rectangle((0, 0.10), 2.4, 0.10,
                 facecolor=LAYER_COLORS["copper"],
                 edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=3))
    ax.add_patch(mpatches.Rectangle((0, 0.20), 2.4, 0.60,
                 facecolor=LAYER_COLORS["substrate"], zorder=1))
    # Centered signal strip at mid-height, thickness t
    strip_y = 0.48
    strip_t = 0.04
    ax.add_patch(mpatches.Rectangle((0.90, strip_y), 0.60, strip_t,
                 facecolor=LAYER_COLORS["copper"],
                 edgecolor=LAYER_COLORS["copper_edge"], lw=0.5, zorder=4))

    # Dimensions
    _dim_h(ax, 0.90, 1.50, strip_y + strip_t + 0.06, "W")
    _dim_v(ax, 0.20, 0.80, 1.68, "b",
           color=LAYER_COLORS["dim_alt"])
    _dim_v(ax, strip_y, strip_y + strip_t, 0.85, "t",
           color=LAYER_COLORS["dim_special"])

    ax.text(0.03, 0.85, "GND", color=LAYER_COLORS["text"],
            fontsize=8, va="center")
    ax.text(0.03, 0.14, "GND", color=LAYER_COLORS["text"],
            fontsize=8, va="center")
    ax.text(0.03, 0.50, "εr", color=LAYER_COLORS["text"],
            fontsize=9, style="italic", va="center")
    ax.text(1.20, strip_y - 0.04, "signal", ha="center", va="top",
            fontsize=7, color=LAYER_COLORS["text"])

    ax.set_xlim(-0.05, 2.45)
    ax.set_ylim(0.05, 1.05)


# ----------------------------------------------------------------------
# Matching (single shunt stub)
# ----------------------------------------------------------------------
def draw_matching_stub(ax, open_circuit: bool = True):
    _style(ax, "Single-stub match (shunt, "
               + ("open" if open_circuit else "short") + ")")
    # Draw a main line from left to right, a tee junction, a vertical stub
    main_y = 0.50
    main_x0 = 0.10
    main_xl = 1.10   # T-junction position (distance d from load)
    main_xr = 1.80   # load position
    stub_len = 0.42

    # Main line
    ax.plot([main_x0, main_xr], [main_y, main_y],
            color=LAYER_COLORS["copper"], lw=4, solid_capstyle="butt",
            zorder=2)
    # Stub (shunt — drawn going up)
    ax.plot([main_xl, main_xl], [main_y, main_y + stub_len],
            color=LAYER_COLORS["copper"], lw=4, solid_capstyle="butt",
            zorder=2)
    # T-junction dot
    ax.add_patch(mpatches.Circle((main_xl, main_y), 0.025,
                 facecolor=LAYER_COLORS["copper"], zorder=3))
    # Load at right end (rectangle representing antenna / Z_A)
    ax.add_patch(mpatches.Rectangle((main_xr, main_y - 0.10), 0.18, 0.20,
                 facecolor=LAYER_COLORS["dim_alt"],
                 edgecolor=LAYER_COLORS["axis"], zorder=3))
    ax.text(main_xr + 0.09, main_y, "Z_A",
            ha="center", va="center", fontsize=9, color="black",
            fontweight="bold")
    # Stub terminal
    if open_circuit:
        # Open — tiny gap at end
        ax.plot([main_xl - 0.06, main_xl + 0.06],
                [main_y + stub_len, main_y + stub_len],
                color=LAYER_COLORS["copper"], lw=2)
    else:
        # Short — thick strike to ground
        ax.plot([main_xl - 0.1, main_xl + 0.1],
                [main_y + stub_len, main_y + stub_len],
                color=LAYER_COLORS["text"], lw=2.5)
        for k in range(5):
            xoff = -0.08 + k * 0.04
            ax.plot([main_xl + xoff, main_xl + xoff + 0.03],
                    [main_y + stub_len, main_y + stub_len + 0.05],
                    color=LAYER_COLORS["text"], lw=1.2)

    # SMA source at left end
    ax.add_patch(mpatches.Circle((main_x0, main_y), 0.06, fill=False,
                 edgecolor=LAYER_COLORS["dim"], lw=1.0, ls=":", zorder=4))
    ax.text(main_x0, main_y - 0.12, "SMA (Z₀)", ha="center", va="top",
            fontsize=8, color=LAYER_COLORS["dim"])

    # Dimensions
    _dim_h(ax, main_xl, main_xr, main_y - 0.22, "d (→ load)")
    _dim_v(ax, main_y, main_y + stub_len, main_xl + 0.12, "l (stub)",
           color=LAYER_COLORS["dim_alt"])

    ax.set_xlim(0.0, 2.10)
    ax.set_ylim(0.20, 1.05)
