"""
Coaxial transmission line — impedance, cutoff, synthesis.

Z0 = (60/√εr) · ln(D/d)
    D = dielectric outer diameter (inside of outer conductor)
    d = inner conductor diameter
    εr = dielectric constant between inner and outer

Higher-order mode cutoff (TE11):
    f_c(TE11) ≈ c / (π·(D+d)/2·√εr)   — rough, first radial mode.
A common operating rule: keep f < f_c(TE11).
"""
from __future__ import annotations
import numpy as np
from .physics import C_LIGHT


def impedance_from_diameters(d: float, D: float, er: float) -> float:
    """Z0 given inner diameter d, outer diameter D, dielectric εr."""
    if d <= 0 or D <= 0 or D <= d:
        raise ValueError("Need 0 < d < D")
    return (60.0 / np.sqrt(er)) * np.log(D / d)


def outer_from_inner(d: float, z0: float, er: float) -> float:
    """Solve for outer diameter D given inner d and target Z0."""
    return d * np.exp((z0 * np.sqrt(er)) / 60.0)


def inner_from_outer(D: float, z0: float, er: float) -> float:
    """Solve for inner diameter d given outer D and target Z0."""
    return D / np.exp((z0 * np.sqrt(er)) / 60.0)


def te11_cutoff(d: float, D: float, er: float) -> float:
    """First higher-order mode cutoff frequency (approx)."""
    return C_LIGHT / (np.pi * 0.5 * (d + D) * np.sqrt(er))


def velocity_factor(er: float) -> float:
    return 1.0 / np.sqrt(er)


def capacitance_per_length(d: float, D: float, er: float) -> float:
    """Farads per meter."""
    from .physics import EPS0
    return 2 * np.pi * EPS0 * er / np.log(D / d)


def inductance_per_length(d: float, D: float) -> float:
    """Henries per meter (non-magnetic dielectric)."""
    from .physics import MU0
    return (MU0 / (2 * np.pi)) * np.log(D / d)


SMA_DEFAULTS = {
    "pin_mm": 1.27,          # SMA center pin
    "teflon_od_mm": 4.10,    # PTFE dielectric outer diameter
    "pTFE_er": 2.08,         # PTFE εr
}
