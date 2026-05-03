"""
CAD-style dimension drawing on matplotlib axes.

Real CAD drawings use extension lines (witness lines) perpendicular to the
dimension axis, with the dimension line offset away from the feature. Text
sits on top of the dimension line. This module mimics that.
"""
from __future__ import annotations

import numpy as np
from matplotlib.patches import FancyArrowPatch, Rectangle
from matplotlib.lines import Line2D
from matplotlib.transforms import blended_transform_factory


# Layer palette — PCB-stackup-inspired
LAYER_COLORS = {
    "substrate":   "#1f5d2e",   # green solder-mask look
    "substrate_lt":"#2b7a3f",
    "copper":      "#d4a24a",   # top copper
    "copper_edge": "#8b6a1e",
    "ground":      "#3c3c3c",
    "silkscreen":  "#f0f0f0",
    "keepout":     "#c04040",
    "drill":       "#ffffff",
    "dielectric":  "#9e7433",
    "pec":         "#cfcfd4",
    "wire":        "#c0c0c8",
    "dim":         "#00e0b4",   # teal dimension text
    "dim_alt":     "#ffd34d",   # yellow secondary dimension
    "dim_special": "#ff7ab6",   # magenta for angle / special
    "grid":        "#333333",
    "bg":          "#1a1a1a",
    "panel_bg":    "#242424",
    "axis":        "#888888",
    "text":        "#e0e0e0",
}

DIM_FONTSIZE = 9
ARROW_STYLE = "<|-|>"
ARROW_MUT = 10


def style_ax(fig, ax, title: str = "", equal: bool = True, grid: bool = True):
    """Uniform dark-theme styling for CAD axes."""
    fig.patch.set_facecolor(LAYER_COLORS["panel_bg"])
    ax.set_facecolor(LAYER_COLORS["bg"])
    if grid:
        ax.grid(True, color=LAYER_COLORS["grid"], lw=0.4, alpha=0.7, zorder=0)
    ax.tick_params(colors=LAYER_COLORS["text"], labelsize=8)
    for sp in ax.spines.values():
        sp.set_color(LAYER_COLORS["axis"])
    if title:
        ax.set_title(title, color=LAYER_COLORS["text"], fontsize=11, pad=10)
    if equal:
        ax.set_aspect("equal", adjustable="datalim")


def _unit_vec(dx, dy):
    L = np.hypot(dx, dy)
    if L < 1e-12:
        return 0.0, 0.0, 0.0
    return dx / L, dy / L, L


def dim_linear(ax, p1, p2, text: str, *,
               offset: float, side: str = "auto",
               color: str = None, fontsize: int = DIM_FONTSIZE,
               ext_gap: float = None, ext_over: float = None,
               show_ext: bool = True, z: int = 5):
    """Draw a CAD-style linear dimension between p1 and p2.

    `offset` shifts the dimension line perpendicular to the (p1→p2) axis.
    Positive offset goes to the "left" of the direction p1→p2 (right-hand rule
    in 2D, i.e., rotate +90° ccw). `side="flip"` flips it.
    """
    color = color or LAYER_COLORS["dim"]
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    dx, dy = p2 - p1
    ux, uy, L = _unit_vec(dx, dy)
    if L == 0:
        return
    # perpendicular (ccw 90°)
    nx, ny = -uy, ux
    if side == "flip":
        nx, ny = -nx, -ny
        offset = abs(offset)
    if side == "-":
        offset = -abs(offset)

    if ext_gap is None:
        ext_gap = 0.02 * L
    if ext_over is None:
        ext_over = 0.04 * L

    # dimension line endpoints (offset away from feature)
    d1 = p1 + np.array([nx, ny]) * offset
    d2 = p2 + np.array([nx, ny]) * offset

    if show_ext:
        # extension line from just outside feature to just past dim line
        sign = np.sign(offset) if offset != 0 else 1.0
        e1a = p1 + np.array([nx, ny]) * (sign * ext_gap)
        e1b = d1 + np.array([nx, ny]) * (sign * ext_over)
        e2a = p2 + np.array([nx, ny]) * (sign * ext_gap)
        e2b = d2 + np.array([nx, ny]) * (sign * ext_over)
        ax.add_line(Line2D([e1a[0], e1b[0]], [e1a[1], e1b[1]],
                           color=color, lw=0.7, zorder=z))
        ax.add_line(Line2D([e2a[0], e2b[0]], [e2a[1], e2b[1]],
                           color=color, lw=0.7, zorder=z))

    # dimension line (arrow both ends)
    arrow = FancyArrowPatch(d1, d2, arrowstyle=ARROW_STYLE,
                             mutation_scale=ARROW_MUT, color=color,
                             lw=0.9, shrinkA=0, shrinkB=0, zorder=z)
    ax.add_patch(arrow)

    # text at midpoint, on top of the line, rotated with it
    mid = (d1 + d2) / 2
    angle_deg = np.degrees(np.arctan2(uy, ux))
    if angle_deg > 90:
        angle_deg -= 180
    elif angle_deg < -90:
        angle_deg += 180
    # shove text outward a touch so it doesn't overlap line
    text_offset = max(0.015 * L, 1e-9)
    tp = mid + np.array([nx, ny]) * np.sign(offset) * text_offset
    ax.text(tp[0], tp[1], text, color=color, fontsize=fontsize,
            ha="center", va="center", rotation=angle_deg,
            rotation_mode="anchor",
            bbox=dict(facecolor=LAYER_COLORS["bg"], edgecolor="none",
                      pad=1.5, alpha=0.75),
            zorder=z + 1)


def dim_horizontal(ax, x1, x2, y, text, **kw):
    """Convenience wrapper — dimension along x with dim line offset to y.
    If caller passes `offset`, it is honored (positive = further from ax origin)."""
    kw.setdefault("offset", 0)
    dim_linear(ax, (x1, y), (x2, y), text, **kw)


def dim_vertical(ax, y1, y2, x, text, **kw):
    kw.setdefault("offset", 0)
    dim_linear(ax, (x, y1), (x, y2), text, **kw)


def dim_radial(ax, center, radius, angle_deg, text, *, color=None, z=5,
               fontsize=DIM_FONTSIZE):
    """Radius dimension — arrow from center to radius point at `angle_deg`."""
    color = color or LAYER_COLORS["dim"]
    a = np.radians(angle_deg)
    cx, cy = center
    rx, ry = cx + radius * np.cos(a), cy + radius * np.sin(a)
    arrow = FancyArrowPatch((cx, cy), (rx, ry), arrowstyle="-|>",
                             mutation_scale=ARROW_MUT, color=color, lw=0.9,
                             shrinkA=0, shrinkB=0, zorder=z)
    ax.add_patch(arrow)
    mid = np.array([(cx + rx) / 2, (cy + ry) / 2])
    # perpendicular nudge
    nx, ny = -np.sin(a), np.cos(a)
    tp = mid + np.array([nx, ny]) * (0.08 * radius)
    ax.text(tp[0], tp[1], text, color=color, fontsize=fontsize,
            ha="center", va="center",
            bbox=dict(facecolor=LAYER_COLORS["bg"], edgecolor="none",
                      pad=1.5, alpha=0.75),
            zorder=z + 1)


def dim_diameter(ax, center, radius, text, *, angle_deg=45, color=None,
                 fontsize=DIM_FONTSIZE, z=5):
    """Diameter dimension crossing the circle center."""
    color = color or LAYER_COLORS["dim"]
    a = np.radians(angle_deg)
    cx, cy = center
    p1 = (cx - radius * np.cos(a), cy - radius * np.sin(a))
    p2 = (cx + radius * np.cos(a), cy + radius * np.sin(a))
    arrow = FancyArrowPatch(p1, p2, arrowstyle=ARROW_STYLE,
                             mutation_scale=ARROW_MUT, color=color, lw=0.9,
                             shrinkA=0, shrinkB=0, zorder=z)
    ax.add_patch(arrow)
    ax.text(cx, cy, text, color=color, fontsize=fontsize,
            ha="center", va="center",
            bbox=dict(facecolor=LAYER_COLORS["bg"], edgecolor="none",
                      pad=1.5, alpha=0.85),
            zorder=z + 1)


def leader(ax, feature_xy, text_xy, text, *, color=None, fontsize=DIM_FONTSIZE,
           z=6):
    """Leader/callout line from the text to a feature with a bent arrow."""
    color = color or LAYER_COLORS["dim_alt"]
    fx, fy = feature_xy
    tx, ty = text_xy
    # two-segment leader: horizontal landing + diagonal to feature
    landing = 0.08 * max(1e-9, abs(tx - fx) + abs(ty - fy))
    lx = tx + (landing if fx > tx else -landing)
    ax.add_line(Line2D([tx, lx], [ty, ty], color=color, lw=0.7, zorder=z))
    arrow = FancyArrowPatch((lx, ty), (fx, fy), arrowstyle="-|>",
                             mutation_scale=ARROW_MUT * 0.8, color=color,
                             lw=0.7, zorder=z)
    ax.add_patch(arrow)
    ax.text(tx, ty, text, color=color, fontsize=fontsize,
            ha="right" if fx > tx else "left", va="center",
            bbox=dict(facecolor=LAYER_COLORS["bg"], edgecolor="none",
                      pad=1.5, alpha=0.75),
            zorder=z + 1)


def angle_dim(ax, vertex, p1, p2, text, *, radius=None, color=None,
              fontsize=DIM_FONTSIZE, z=5):
    """Arc dimension for an angle at `vertex`, spanning from p1 direction to p2 direction."""
    from matplotlib.patches import Arc, FancyArrowPatch
    color = color or LAYER_COLORS["dim_special"]
    vx, vy = vertex
    a1 = np.degrees(np.arctan2(p1[1] - vy, p1[0] - vx))
    a2 = np.degrees(np.arctan2(p2[1] - vy, p2[0] - vx))
    if radius is None:
        radius = 0.5 * min(np.hypot(p1[0] - vx, p1[1] - vy),
                           np.hypot(p2[0] - vx, p2[1] - vy))
    arc = Arc(vertex, 2 * radius, 2 * radius, angle=0,
              theta1=min(a1, a2), theta2=max(a1, a2),
              color=color, lw=0.9, zorder=z)
    ax.add_patch(arc)
    mid = np.radians((a1 + a2) / 2)
    tx = vx + (radius + 0.12 * radius) * np.cos(mid)
    ty = vy + (radius + 0.12 * radius) * np.sin(mid)
    ax.text(tx, ty, text, color=color, fontsize=fontsize,
            ha="center", va="center",
            bbox=dict(facecolor=LAYER_COLORS["bg"], edgecolor="none",
                      pad=1.5, alpha=0.75),
            zorder=z + 1)


def add_scale_bar(ax, length: float, label: str, *, loc: str = "lower right",
                  color: str = None):
    """Small scale bar in the axes corner."""
    color = color or LAYER_COLORS["text"]
    tr = blended_transform_factory(ax.transAxes, ax.transAxes)
    # We need to know data extents to draw a length-scaled bar
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    dx = x1 - x0
    frac = length / dx if dx > 0 else 0.2
    frac = min(frac, 0.35)
    if loc == "lower right":
        bx0 = 0.95 - frac
        bx1 = 0.95
        by = 0.06
    else:
        bx0, bx1, by = 0.05, 0.05 + frac, 0.06
    ax.plot([bx0, bx1], [by, by], color=color, lw=2.5, transform=ax.transAxes,
            solid_capstyle="butt", zorder=20)
    ax.plot([bx0, bx0], [by - 0.015, by + 0.015], color=color, lw=2.5,
            transform=ax.transAxes, zorder=20)
    ax.plot([bx1, bx1], [by - 0.015, by + 0.015], color=color, lw=2.5,
            transform=ax.transAxes, zorder=20)
    ax.text((bx0 + bx1) / 2, by + 0.03, label, color=color, ha="center",
            va="bottom", fontsize=8, transform=ax.transAxes, zorder=20)


def add_layer_legend(ax, items: list[tuple[str, str]], *, loc="upper right"):
    """Draw a small layer legend block. `items` is [(color, label), ...]."""
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=c, edgecolor=LAYER_COLORS["axis"], label=lbl)
               for c, lbl in items]
    leg = ax.legend(handles=handles, loc=loc, facecolor=LAYER_COLORS["panel_bg"],
                    edgecolor=LAYER_COLORS["axis"], labelcolor=LAYER_COLORS["text"],
                    fontsize=8, framealpha=0.85)
    leg.set_zorder(30)
