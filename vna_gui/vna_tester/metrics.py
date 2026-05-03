"""
Antenna figures-of-merit derived from S11 (or S22) traces.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .trace import Trace


@dataclass
class AntennaMetrics:
    f_resonance_hz: float           # frequency at which S11 is minimum
    s11_min_db: float               # minimum return loss
    vswr_at_resonance: float
    f_low_m10db_hz: Optional[float] # left edge of -10 dB band (None if never)
    f_high_m10db_hz: Optional[float]
    bandwidth_m10db_hz: float       # 0 if no -10 dB region
    fractional_bw_pct: float        # BW / fc * 100
    impedance_at_resonance: complex
    quality_factor: float           # fc / BW (loaded Q estimate)
    pass_minus10db: bool            # does the entire trace stay below -10 dB?
    mismatch_loss_db: float         # at resonance


def antenna_metrics(trace: Trace, z0: float = 50.0,
                    target_db: float = -10.0) -> AntennaMetrics:
    if trace.freq.size == 0:
        return AntennaMetrics(0, 0, 1, None, None, 0, 0, 0+0j, 0, False, 0)

    f = trace.freq
    s = trace.s
    db = trace.magnitude_db()
    idx_min = int(np.argmin(db))
    f_res = float(f[idx_min])
    s11_min = float(db[idx_min])

    m = min(abs(s[idx_min]), 0.999_999)
    vswr_res = (1.0 + m) / (1.0 - m)

    # -10 dB bandwidth around the resonance
    below = db <= target_db
    f_low = f_high = None
    bw = 0.0
    fc = f_res
    if below.any():
        # walk left & right from resonance
        left = idx_min
        while left > 0 and below[left - 1]:
            left -= 1
        right = idx_min
        while right < below.size - 1 and below[right + 1]:
            right += 1
        f_low = float(f[left])
        f_high = float(f[right])
        bw = max(0.0, f_high - f_low)
        fc = 0.5 * (f_low + f_high)

    fractional = (bw / fc * 100.0) if fc > 0 else 0.0
    s_res = s[idx_min]
    if abs(1.0 - s_res) > 1e-9:
        z_res = z0 * (1.0 + s_res) / (1.0 - s_res)
    else:
        z_res = complex(float("inf"), 0.0)

    q_loaded = (fc / bw) if bw > 0 else 0.0
    pass_all = bool(np.all(below))
    mismatch_loss = -10.0 * np.log10(max(1e-12, 1.0 - abs(s_res) ** 2))

    return AntennaMetrics(
        f_resonance_hz=f_res,
        s11_min_db=s11_min,
        vswr_at_resonance=vswr_res,
        f_low_m10db_hz=f_low,
        f_high_m10db_hz=f_high,
        bandwidth_m10db_hz=bw,
        fractional_bw_pct=fractional,
        impedance_at_resonance=z_res,
        quality_factor=q_loaded,
        pass_minus10db=pass_all,
        mismatch_loss_db=mismatch_loss,
    )


def format_freq(hz: float) -> str:
    if hz >= 1e9:
        return f"{hz/1e9:.4f} GHz"
    if hz >= 1e6:
        return f"{hz/1e6:.3f} MHz"
    if hz >= 1e3:
        return f"{hz/1e3:.3f} kHz"
    return f"{hz:.0f} Hz"


def format_z(z: complex) -> str:
    if not np.isfinite(z.real) or not np.isfinite(z.imag):
        return "∞"
    sign = "+" if z.imag >= 0 else "-"
    return f"{z.real:.2f} {sign} j{abs(z.imag):.2f} Ω"
