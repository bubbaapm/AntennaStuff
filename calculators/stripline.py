"""
Balanced stripline — trace between two ground planes in homogeneous dielectric.

References: Cohn (1954), Wheeler / Wadell approximations.

Geometry
--------
    ═══════════════════   ← top ground
       |  W  |            ← center conductor at mid-height
       b (full dielectric thickness, top ground → bottom ground)
       εr homogeneous
    ═══════════════════   ← bottom ground
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import brentq
from .physics import ETA0


def analyze(W: float, b: float, er: float, t: float = 0.0) -> dict:
    """Return Z0 for a centered stripline trace of width W in dielectric thickness b.

    Uses the classical Cohn formula for zero-thickness trace; for finite t the
    Wheeler correction is applied.
    """
    if W <= 0 or b <= 0:
        raise ValueError("W, b must be > 0")

    # Zero-thickness:
    # Z0 = (60/√εr) · ln(4b / (0.67π·(0.8W + t)))  for W/(b-t) > 0.35
    # otherwise different formula — use the effective-width correction.
    m = 6 * b / (3 * b + t) if t > 0 else 2.0
    We = W + (t / np.pi) * (1 + np.log((2 * b / t + (b / t + 1)) if t > 0 else 1e30))
    # simpler: Cohn approximation
    Z0 = (30 * np.pi / np.sqrt(er)) / (We / b + 0.441 * (1 - (t / b if t > 0 else 0.0)))
    return {"Z0": Z0, "Ereff": er, "W_eff": We}


def synthesize(z0: float, er: float, b: float, t: float = 0.0) -> dict:
    """Solve for W given target Z0."""
    def f(W):
        return analyze(W, b, er, t)["Z0"] - z0
    lo = 1e-7 * b
    hi = 100 * b
    if f(lo) * f(hi) > 0:
        return {"W": np.nan, "error": "No solution"}
    W = brentq(f, lo, hi, xtol=1e-10)
    return {"W": W, "Z0": analyze(W, b, er, t)["Z0"], "Ereff": er}
