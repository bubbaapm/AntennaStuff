"""
High-resolution image export.

Two strategies:

  • Per-plot:  use the panel's own export_image() — pyqtgraph's
    ImageExporter and matplotlib.savefig both *re-render* at the requested
    resolution, so the output is sharp regardless of the on-screen size.

  • Whole-window composite: render each plot panel to a high-res QImage
    via its native exporter, then paint them onto a target QImage in their
    grid positions. This avoids the "blow up the bitmap" trap.
"""
from __future__ import annotations
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtCore import QRect, QRectF, Qt, QSize
from PyQt6.QtGui import QImage, QPainter, QColor, QFont
from PyQt6.QtWidgets import QWidget

from .base import PlotPanel


def export_panel(panel: PlotPanel, path: str,
                 size: Tuple[int, int] = (1920, 1080),
                 fmt: str = "png") -> bool:
    """Export a single plot panel to disk at the given pixel size."""
    return panel.export_image(path, size[0], size[1], fmt=fmt)


def export_grid_composite(panels: List[PlotPanel], path: str,
                          target_size: Tuple[int, int] = (3840, 2160),
                          background: str = "#1d1d1d",
                          title: str = "",
                          fmt: str = "png") -> bool:
    """
    Render `panels` into one image at `target_size`. Each panel is rendered
    individually at high resolution via its own exporter, then composited
    by current grid layout (taken from each panel's geometry).

    Falls back to a simple bitmap upscale only if a panel has no working
    exporter.
    """
    if not panels:
        return False

    W, H = target_size
    # Determine layout from screen geometry — find bounding box
    rects: List[QRect] = []
    for p in panels:
        g = p.geometry()
        if g.width() <= 0 or g.height() <= 0:
            return False
        rects.append(g)
    bx = min(r.x() for r in rects)
    by = min(r.y() for r in rects)
    bw = max(r.x() + r.width() for r in rects) - bx
    bh = max(r.y() + r.height() for r in rects) - by
    if bw <= 0 or bh <= 0:
        return False

    out = QImage(W, H, QImage.Format.Format_ARGB32)
    out.fill(QColor(background))

    sx = W / bw
    sy = H / bh

    painter = QPainter(out)
    try:
        if title:
            painter.setPen(QColor("#e0e0e0"))
            f = QFont("Segoe UI", max(10, int(0.018 * H)))
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(int(0.02 * W), int(0.04 * H), title)

        with tempfile.TemporaryDirectory() as tmpdir:
            for i, p in enumerate(panels):
                g = p.geometry()
                tx = int((g.x() - bx) * sx)
                ty = int((g.y() - by) * sy)
                tw = max(1, int(g.width() * sx))
                th = max(1, int(g.height() * sy))
                tmp = str(Path(tmpdir) / f"panel_{i}.png")
                ok = p.export_image(tmp, tw, th, fmt="png")
                if ok and Path(tmp).exists():
                    img = QImage(tmp)
                    if not img.isNull():
                        painter.drawImage(QRect(tx, ty, tw, th),
                                          img.scaled(tw, th,
                                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
                        continue
                # fallback: render the QWidget at its current res, scale up
                pix = p.grab()
                painter.drawImage(QRect(tx, ty, tw, th),
                                  pix.toImage().scaled(tw, th,
                                                       Qt.AspectRatioMode.IgnoreAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))
    finally:
        painter.end()

    return out.save(path, fmt.upper() if fmt else None, 95)


def export_widget_screenshot(widget: QWidget, path: str,
                             upscale: float = 1.0,
                             fmt: str = "png") -> bool:
    """
    Plain-widget screenshot at native resolution × `upscale`. Use when
    the user wants exactly what they see (e.g. for documentation).

    For real high-res, prefer export_grid_composite.
    """
    pix = widget.grab()
    if upscale != 1.0:
        new_size = QSize(int(pix.width() * upscale), int(pix.height() * upscale))
        pix = pix.scaled(new_size,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return pix.save(path, fmt.upper() if fmt else None, 95)
