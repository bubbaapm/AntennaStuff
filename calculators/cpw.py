"""
Coplanar Waveguide (CPW) and Grounded CPW (CPWG / CBCPW) synthesis & analysis.

References
----------
Simons, R. N. *Coplanar Waveguide Circuits, Components, and Systems* (2001).
Wadell, B. C. *Transmission Line Design Handbook* (1991).
Conformal-mapping closed-form approximations — accurate within ≈1 % of full-wave
solutions for typical PCB geometries (s/h < 2, w/h < 1, εr < 10).

Geometry
--------
        <--- b --->
    |=======|---|=======|    ← top metal (ground | signal | ground)
    |       | s |       |
    substrate (h, εr)
    |============|           ← bottom ground (only for CPWG)

    s = signal trace width
    w = gap between signal and coplanar ground
    b = s + 2w  (total aperture)
    h = substrate thickness

All distances in meters, all impedances in ohms.
"""
from __future__ import annotations
import numpy as np
from scipy.special import ellipk
from scipy.optimize import brentq
from .physics import ETA0


def _kkp(k: float) -> float:
    """Return K(k) / K(k') where k' = sqrt(1 - k²). Uses scipy m = k²."""
    k = np.clip(k, 1e-12, 1.0 - 1e-12)
    m = k * k
    mp = 1 - m
    return ellipk(m) / ellipk(mp)


def analyze_cpw(s: float, w: float, er: float, h: float = None,
                grounded: bool = False) -> dict:
    """Analysis: given geometry (s, w, h, εr, ground?), return (Z0, εr_eff).

    If `grounded=False` or h is None, treats substrate as semi-infinite (pure CPW).
    If `grounded=True` and h is finite, uses CPWG conformal mapping.
    """
    if s <= 0 or w <= 0:
        raise ValueError("s and w must be positive")

    k = s / (s + 2 * w)
    r1 = _kkp(k)

    if grounded and h is not None and h > 0:
        k1 = np.tanh(np.pi * s / (4 * h)) / np.tanh(np.pi * (s + 2 * w) / (4 * h))
        r2 = _kkp(k1)
        ereff = (1 + er * r2 / r1) / (1 + r2 / r1)
        z0 = (60 * np.pi / np.sqrt(ereff)) / (r1 + r2)
    else:
        ereff = (er + 1) / 2
        z0 = (30 * np.pi / np.sqrt(ereff)) / r1
    return {"Z0": z0, "Ereff": ereff, "k": k}


def synthesize_cpw(z0: float, er: float, h: float, w: float = None,
                   grounded: bool = False, s_guess: float = None) -> dict:
    """Synthesize CPW geometry for target Z0.

    Holding `w` (gap) constant, solve for `s` that gives Z0. Default w = h/2.
    """
    if w is None:
        w = (h or 0.5e-3) / 2
    if s_guess is None:
        s_guess = w

    lo = 1e-6 * max(w, 1e-6)
    hi = 1000 * w

    def f(s):
        return analyze_cpw(s, w, er, h, grounded)["Z0"] - z0

    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        # Try swapping direction
        return {"W": np.nan, "error": "No root for this gap — try a different w"}
    s = brentq(f, lo, hi, xtol=1e-9)
    ana = analyze_cpw(s, w, er, h, grounded)
    return {"s": s, "w": w, "b": s + 2 * w,
            "Z0": ana["Z0"], "Ereff": ana["Ereff"]}


def synthesize_cpw_fixed_s(z0: float, er: float, h: float, s: float,
                            grounded: bool = False) -> dict:
    """Synthesize with fixed signal width s — solve for w (gap)."""
    lo = 1e-8
    hi = 1000 * s

    def f(w):
        return analyze_cpw(s, w, er, h, grounded)["Z0"] - z0

    flo = f(lo)
    fhi = f(hi)
    if flo * fhi > 0:
        return {"W": np.nan, "error": "No root for this signal width"}
    w = brentq(f, lo, hi, xtol=1e-10)
    ana = analyze_cpw(s, w, er, h, grounded)
    return {"s": s, "w": w, "b": s + 2 * w,
            "Z0": ana["Z0"], "Ereff": ana["Ereff"]}
