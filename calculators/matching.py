"""
Matching network synthesis.

- Quarter-wave transformer
- Single open-circuit shunt stub (microstrip)
- Single short-circuit shunt stub
- L-network (lumped)
- Smith-chart-ready utilities (reflection coefficient → arc trajectory)
"""
from __future__ import annotations
import numpy as np
from .physics import C_LIGHT


# ----------------------------------------------------------------------------
# Quarter-wave transformer
# ----------------------------------------------------------------------------

def quarter_wave(z_load: float, z_source: float) -> dict:
    """Real load to real source via λ/4 of impedance √(ZL·Zs)."""
    if z_load <= 0 or z_source <= 0:
        raise ValueError("Loads must be real and positive for a simple λ/4")
    z_trans = np.sqrt(z_load * z_source)
    return {"Z_transformer": z_trans}


# ----------------------------------------------------------------------------
# Single shunt stub matcher
# ----------------------------------------------------------------------------

def shunt_stub(z_load: complex, z0: float = 50.0,
               open_circuit: bool = True) -> list[dict]:
    """Single shunt stub matching network.

    Returns up to two solutions, each with:
        d_over_lambda : line length from load to stub junction (in λ_g)
        l_over_lambda : stub length (in λ_g)

    Assumes all lines have characteristic impedance z0 and the same guided
    wavelength (homogeneous medium).
    """
    yL = 1.0 / z_load
    y0 = 1.0 / z0
    # normalize
    yL_n = yL * z0    # normalized load admittance
    gL, bL = yL_n.real, yL_n.imag

    solutions = []
    # From Pozar Sec 5.2: we need the line section `d` such that Y_in(d) has
    # normalized conductance = 1 (i.e., real part 1 on the y chart).
    # Equivalent formula:
    if np.isclose(gL, 1.0):
        # Trivial — already on g=1 circle
        ts = [0, np.tan(np.pi)]
    else:
        # standard two-solution form (Pozar eq 5.20)
        arg_num = bL + np.sqrt(gL * ((1 - gL) ** 2 + bL ** 2)) / (max(1 - gL, 1e-12))
        # two roots:
        discr = gL * ((1 - gL) ** 2 + bL ** 2)
        if discr < 0 or (1 - gL) == 0:
            return []
        r = np.sqrt(discr)
        t1 = (bL + r) / (1 - gL)
        t2 = (bL - r) / (1 - gL)
        ts = [t1, t2]

    for t in ts:
        d = (1 / (2 * np.pi)) * np.arctan(t) if t >= 0 else \
            (1 / (2 * np.pi)) * (np.pi + np.arctan(t))
        # susceptance seen at junction
        B = (gL ** 2 * t - (1 - bL * t) * (bL + t)) / \
            (gL * (1 + t ** 2))   # normalized

        # stub must cancel B  → stub susceptance = -B
        if open_circuit:
            # open stub: Y_stub / y0 = j·tan(βl)
            # want tan(βl) = -B
            l = (1 / (2 * np.pi)) * (np.arctan(-B) % np.pi)
        else:
            # short stub: Y_stub/y0 = -j·cot(βl)
            # want -cot(βl) = -B → cot(βl) = B → tan(βl) = 1/B
            if abs(B) < 1e-12:
                l = 0.25
            else:
                l = (1 / (2 * np.pi)) * (np.arctan(1 / B) % np.pi)

        solutions.append({"d_over_lambda": d % 1.0,
                          "l_over_lambda": l % 1.0,
                          "B_junction": B})
    return solutions


def physical_stub_lengths(solution: dict, guided_lambda: float) -> dict:
    d = solution["d_over_lambda"] * guided_lambda
    l = solution["l_over_lambda"] * guided_lambda
    return {"d": d, "l": l}


# ----------------------------------------------------------------------------
# L-network (lumped, two components) — for narrow-band matching.
# ----------------------------------------------------------------------------

def l_network(z_load: complex, z_source: float, freq_hz: float) -> list[dict]:
    """Lumped L-network between real source and complex load.

    Returns up to two topologies (series-first and shunt-first) each with the
    required reactances and corresponding C/L values.
    """
    Rs = z_source
    RL, XL = z_load.real, z_load.imag
    w = 2 * np.pi * freq_hz
    solutions = []

    if RL > Rs:
        # Shunt element next to load, series element next to source
        Q = np.sqrt(RL / Rs - 1 + (XL ** 2) / (RL * Rs))
        for sign in (+1, -1):
            Xs = sign * Q * Rs
            # Shunt reactance on load side
            Xp_num = RL * (1 - 0) if False else None
            # Pozar eq 5.4 — solve directly:
            Bp = (XL + sign * np.sqrt((RL / Rs) * (RL ** 2 + XL ** 2 - Rs * RL))) \
                 / (RL ** 2 + XL ** 2)
            solutions.append(_lc_from_X(Xs, Bp, w, "source-series, load-shunt"))
    else:
        # Rs > RL — shunt on source side, series on load side
        Q = np.sqrt(Rs / RL - 1)
        for sign in (+1, -1):
            Xs = sign * np.sqrt(RL * (Rs - RL)) - XL
            Bp = sign * np.sqrt((Rs - RL) / RL) / Rs
            solutions.append(_lc_from_X(Xs, Bp, w, "source-shunt, load-series"))

    return solutions


def _lc_from_X(Xs: float, Bp: float, w: float, topology: str) -> dict:
    """Translate reactances to L/C values; negative reactance → capacitor."""
    if Xs > 0:
        L_series = Xs / w
        series_label = f"L = {L_series*1e9:.3f} nH"
    else:
        C_series = -1.0 / (w * Xs)
        series_label = f"C = {C_series*1e12:.3f} pF"
    if Bp > 0:
        C_shunt = Bp / w
        shunt_label = f"C = {C_shunt*1e12:.3f} pF"
    else:
        L_shunt = -1.0 / (w * Bp)
        shunt_label = f"L = {L_shunt*1e9:.3f} nH"
    return {"topology": topology, "Xs": Xs, "Bp": Bp,
            "series": series_label, "shunt": shunt_label}
