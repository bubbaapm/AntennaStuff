"""
Linear phased array (generic) — N isotropic elements, user-defined spacing
and progressive phase β.
"""
from __future__ import annotations
import numpy as np
from matplotlib import patches as mpatches
import warnings
from scipy.signal.windows import chebwin

from .base import AntennaBase, Context, Input, register_antenna, C_LIGHT
from plotting.cad import LAYER_COLORS, style_ax, dim_horizontal, leader


_TAPER_CHOICES = ["uniform", "hamming", "hann", "blackman", "chebyshev"]


def _amplitude_taper(name: str, N: int, sll_dB: float) -> np.ndarray:
    """Return the N-element amplitude window for the given taper name."""
    name = name.strip().lower()
    n = np.arange(N)
    if N < 2:
        return np.ones(N)
    if name.startswith("uni"):
        w = np.ones(N)
    elif name.startswith("ham"):
        w = 0.54 - 0.46 * np.cos(2 * np.pi * n / (N - 1))
    elif name.startswith("han"):
        w = 0.5 - 0.5 * np.cos(2 * np.pi * n / (N - 1))
    elif name.startswith("bla"):
        w = (0.42 - 0.5 * np.cos(2 * np.pi * n / (N - 1))
             + 0.08 * np.cos(4 * np.pi * n / (N - 1)))
    elif name.startswith("che"):
        # scipy's chebwin warns at SLL < 45 dB about spectral-analysis ENBW
        # behavior; that caveat doesn't apply to array tapers, so silence it.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            w = chebwin(N, at=max(10.0, float(sll_dB)))
    else:
        w = np.ones(N)
    peak = np.max(w)
    return w / peak if peak > 0 else w


@register_antenna("Linear Phased Array", category="Array")
class LinearPhasedArray(AntennaBase):
    notes = ("N isotropic elements along x, spacing d (in λ). "
             "AF(θ,φ) = sin(Nψ/2)/(N·sin(ψ/2)) with ψ = k·d·sinθ·cosφ + β.")
    polarization = "set by element (this view shows the array factor only)"
    beam_axis = "scanned: broadside if β=0, end-fire toward +X for β = −k·d"
    bandwidth_note = "set by element BW × beam-squint tolerance"

    def inputs(self):
        return [
            Input("N",         "Number of elements N",    "8"),
            Input("d_lambda",  "Spacing d (λ)",           "0.5"),
            Input("beta_deg",  "Progressive phase β (°)", "0"),
            Input("taper",     "Amplitude taper",         "uniform",
                  choices=_TAPER_CHOICES,
                  tooltip="Uniform → narrowest beam (max gain) but ~−13 dB "
                          "sidelobes. Chebyshev gives the lowest sidelobe for "
                          "a given beamwidth; set the target SLL below."),
            Input("sll_dB",    "Chebyshev sidelobe level (dB, positive)", "25",
                  tooltip="Used only when the taper is Chebyshev."),
        ]

    def compute(self, ctx, params):
        N = int(float(params.get("N", "8")))
        d_lam = float(params.get("d_lambda", "0.5"))
        beta = np.radians(float(params.get("beta_deg", "0")))
        taper = str(params.get("taper", "uniform")).strip().lower()
        sll_dB = float(params.get("sll_dB", "25"))

        d = d_lam * ctx.lambda0
        w = _amplitude_taper(taper, N, sll_dB)

        # Steering direction from β. With AF = sin(Nψ/2)/(N sin(ψ/2)) and
        # ψ = kd sinθ cosφ + β, the main beam sits where ψ = 0, i.e.
        #   sinθ cosφ = −β / (kd).
        # Reported below as the angle from broadside (θ=π/2, φ=0).
        if d > 0:
            sin_main = -beta / (2 * np.pi * d_lam)
            if np.abs(sin_main) <= 1:
                steer_deg = np.degrees(np.arcsin(sin_main))
            else:
                steer_deg = np.nan
        else:
            steer_deg = np.nan
        # Array length
        L_arr = (N - 1) * d
        # Directivity of a uniform broadside array (Hansen): D ≈ 2 N d/λ.
        # With a non-uniform taper, scale by the taper efficiency
        # η_t = (Σ|w|)² / (N · Σ|w|²).
        if np.sum(w * w) > 0:
            taper_eff = (np.sum(w) ** 2) / (N * np.sum(w * w))
        else:
            taper_eff = 1.0
        D_lin = 2 * N * d_lam * taper_eff if d_lam > 0 else N * taper_eff
        D_dBi = 10 * np.log10(max(D_lin, 1e-6))
        return {"N": N, "d": d, "d_lambda": d_lam, "beta_rad": beta,
                "beta_deg": float(params.get("beta_deg", "0")),
                "weights": w, "taper": taper, "sll_dB": sll_dB,
                "taper_eff": taper_eff, "D_dBi": D_dBi,
                "steer_deg": steer_deg, "L_arr": L_arr,
                # board_size = (X_extent, Y_extent). Array runs along +X.
                "board_size": (L_arr, max(d, L_arr * 0.05))}

    def _summary_extra(self, ctx, r):
        m, u = ctx.out_mult, ctx.unit_str
        taper_label = r['taper']
        if r['taper'].startswith('che'):
            taper_label += f"  (SLL target = −{r['sll_dB']:.1f} dB)"
        out = [
            f"  N                = {r['N']}",
            f"  d                = {r['d']*m:.3f} {u}  ({r['d_lambda']:.3f} λ)",
            f"  β (progressive)  = {r['beta_deg']:.2f}°",
            f"  Taper            = {taper_label}",
            f"  Taper efficiency = {r['taper_eff']:.3f}",
            f"  Array length     = {r['L_arr']*m:.3f} {u}",
            f"  Est. directivity = {r['D_dBi']:.2f} dBi  (isotropic-element AF)",
        ]
        if np.isfinite(r['steer_deg']):
            out.append(f"  Steered beam at  = {r['steer_deg']:.2f}° from broadside")
        return out

    def plot_geometry(self, ax, ctx, r):
        m = ctx.out_mult
        d = r["d"] * m
        N = r["N"]
        style_ax(ax.figure, ax, f"Linear Array: N={N}, d={r['d_lambda']:.2f}λ",
                 equal=True)
        weights = r["weights"]
        positions = (np.arange(N) - (N - 1) / 2) * d
        for x, w in zip(positions, weights):
            size = 0.3 * d * (0.5 + 0.5 * w)
            ax.add_patch(mpatches.Circle((x, 0), size,
                                         facecolor=LAYER_COLORS["copper"],
                                         edgecolor=LAYER_COLORS["axis"], zorder=2))
            ax.text(x, -0.9 * d, f"{w:.2f}", ha="center", va="top",
                    fontsize=8, color=LAYER_COLORS["text"])
        ax.plot(positions, np.zeros_like(positions), color="white", lw=0.8, zorder=1)
        dim_horizontal(ax, positions[0], positions[-1], d*1.4,
                       f"L = {(N-1)*d:.2f}", offset=0)
        if N > 1:
            dim_horizontal(ax, positions[0], positions[1], d*0.6,
                           f"d = {d:.2f}", offset=0, color=LAYER_COLORS["dim_alt"])
        ax.set_ylim(-2 * d, 2.2 * d)

    def plot_fields(self, ax, ctx, r):
        # |AF| vs angle from the array axis, with a β-sweep overlay so the
        # designer can see how phase progressively steers the beam.
        style_ax(ax.figure, ax,
                 f"Array Factor — angle from array axis (broadside @ 90°)   "
                 f"taper={r['taper']}",
                 equal=False, grid=True)
        N = r["N"]
        d_lam = r["d_lambda"]
        w = np.asarray(r["weights"], dtype=float)
        w_sum = max(np.sum(w), 1e-12)
        gamma = np.linspace(0, np.pi, 720)
        kd = 2 * np.pi * d_lam
        n_idx = np.arange(N).reshape(-1, 1)
        for b_deg, color in zip([-90, -45, 0, 45, 90],
                                ["#ff7ab6", "#ffd34d", "#00e0b4",
                                 "#4ac0ff", "#c07aff"]):
            b = np.radians(b_deg)
            psi = kd * np.cos(gamma) + b
            AF = np.abs(np.sum(w[:, None] * np.exp(1j * n_idx * psi[None, :]),
                               axis=0) / w_sum)
            ax.plot(np.degrees(gamma), AF, lw=1.3, color=color,
                    label=f"β={b_deg}°")
        ax.axvline(90, color="#555", ls="--", lw=0.7)
        ax.set_xlabel("γ (°) — angle from array axis", color=LAYER_COLORS["text"])
        ax.set_ylabel("|AF|", color=LAYER_COLORS["text"])
        ax.set_xlim(0, 180)
        ax.legend(loc="upper right", facecolor=LAYER_COLORS["panel_bg"],
                  edgecolor=LAYER_COLORS["axis"],
                  labelcolor=LAYER_COLORS["text"], fontsize=8)

    def pattern(self, theta, phi, ctx, r):
        N = r["N"]
        d = r["d"]
        beta = r["beta_rad"]
        w = np.asarray(r["weights"], dtype=float)
        w_sum = max(np.sum(w), 1e-12)
        k0 = 2 * np.pi * ctx.fr / C_LIGHT
        theta_b = np.broadcast_to(theta,
                                  np.broadcast_shapes(theta.shape, phi.shape))
        phi_b = np.broadcast_to(phi,
                                np.broadcast_shapes(theta.shape, phi.shape))
        psi = k0 * d * np.sin(theta_b) * np.cos(phi_b) + beta
        # Direct sum AF = Σ_n w_n exp(j n ψ). Broadcast over the angular grid.
        shape = (N,) + (1,) * psi.ndim
        n_idx = np.arange(N).reshape(shape)
        wn = w.reshape(shape)
        AF = np.sum(wn * np.exp(1j * n_idx * psi[None, ...]), axis=0) / w_sum
        return np.abs(AF)
