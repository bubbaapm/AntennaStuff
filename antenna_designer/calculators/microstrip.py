"""
Microstrip transmission line synthesis and analysis.

Synthesis: Hammerstad-Jensen (IEEE MTT-S 1980) closed-form W/h from (Z0, εr).
Analysis: Wheeler/Hammerstad W/h → Z0, εr_eff.
Dispersion: Getsinger / Kirschning-Jansen correction for frequency effects.

All lengths in meters. All impedances in ohms.
"""
from __future__ import annotations
import numpy as np
from .physics import C_LIGHT, ETA0


def synthesize(z0: float, er: float, h: float) -> dict:
    """Return {W, W_h, Ereff, Z0_check} for target Z0 with substrate εr, h."""
    A = (z0 / 60.0) * np.sqrt((er + 1) / 2) + ((er - 1) / (er + 1)) * (0.23 + 0.11 / er)
    B = (377.0 * np.pi) / (2 * z0 * np.sqrt(er))

    W_h_narrow = (8 * np.exp(A)) / (np.exp(2 * A) - 2)
    if W_h_narrow < 2:
        W_h = W_h_narrow
    else:
        W_h = (2 / np.pi) * (
            B - 1 - np.log(2 * B - 1)
            + ((er - 1) / (2 * er)) * (np.log(B - 1) + 0.39 - 0.61 / er)
        )
    W = W_h * h
    ana = analyze(W, er, h)
    return {
        "W": W,
        "W_h": W_h,
        "Ereff": ana["Ereff"],
        "Z0": ana["Z0"],
        "guided_wavelength": lambda f: C_LIGHT / (f * np.sqrt(ana["Ereff"])),
    }


def analyze(w: float, er: float, h: float) -> dict:
    """Given W, h, εr, compute εr_eff and Z0 (Hammerstad-Jensen)."""
    u = w / h
    # Hammerstad 1980 accurate form
    a = 1 + (1 / 49) * np.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) \
        + (1 / 18.7) * np.log(1 + (u / 18.1) ** 3)
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    ereff = (er + 1) / 2 + ((er - 1) / 2) * (1 + 10 / u) ** (-a * b)
    fu = 6 + (2 * np.pi - 6) * np.exp(-(30.666 / u) ** 0.7528)
    z0_1 = (ETA0 / (2 * np.pi)) * np.log(fu / u + np.sqrt(1 + (2 / u) ** 2))
    z0 = z0_1 / np.sqrt(ereff)
    return {"Ereff": ereff, "Z0": z0, "W_h": u}


def effective_permittivity_dispersion(ereff_dc: float, er: float, z0_dc: float,
                                      h: float, freq: float) -> float:
    """Kirschning-Jansen frequency-dependent εr_eff."""
    fn = freq * h / 1e6  # h in meters * Hz → MHz·m then scale? actually normalized
    # Use the classical Getsinger:
    #   εr_eff(f) = εr - (εr - εr_eff_dc) / (1 + G (f/fT)^2)
    # where fT = z0 / (2 μ0 h), G ≈ 0.6 + 0.009 z0
    fT = z0_dc / (2 * 4e-7 * np.pi * h)
    G = 0.6 + 0.009 * z0_dc
    return er - (er - ereff_dc) / (1 + G * (freq / fT) ** 2)


def attenuation_db_per_m(w: float, h: float, er: float, tan_d: float,
                         freq: float, sigma: float = 5.8e7) -> dict:
    """Conductor + dielectric loss. Returns dict with alpha_c, alpha_d, alpha."""
    from .physics import skin_depth
    ana = analyze(w, er, h)
    ereff = ana["Ereff"]
    z0 = ana["Z0"]
    Rs = np.sqrt(np.pi * freq * 4e-7 * np.pi / sigma)
    alpha_c = Rs / (z0 * w)                           # Np/m, approximate
    k0 = 2 * np.pi * freq / C_LIGHT
    alpha_d = ((er * (ereff - 1)) / (np.sqrt(ereff) * (er - 1))) * \
              (k0 * tan_d / 2)
    to_db = 8.685889638
    return {"alpha_c_dB_per_m": alpha_c * to_db,
            "alpha_d_dB_per_m": alpha_d * to_db,
            "alpha_total_dB_per_m": (alpha_c + alpha_d) * to_db}
