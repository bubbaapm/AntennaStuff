"""
Antenna registry + base class.

Drop a new antenna into a module, decorate it with @register_antenna,
import the module from antennas/__init__.py, and it shows up in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional
import numpy as np

C_LIGHT = 2.99792458e8
ETA0 = 119.9169832 * np.pi  # ≈ 376.73 Ω (free-space impedance)


@dataclass
class Input:
    """Description of one user input field for an antenna."""
    key: str
    label: str
    default: str
    unit: str = ""
    tooltip: str = ""


@dataclass
class Context:
    """Common design inputs, normalized to SI (meters, Hz)."""
    fr: float           # Hz
    er: float           # substrate relative permittivity
    z0: float           # target impedance (Ω)
    h: float            # substrate thickness (m)
    Ls: float           # X-axis substrate margin (m)
    Ws: float           # Y-axis substrate margin (m)
    loss_tangent: float = 0.02     # tan δ — used for efficiency
    cu_thickness: float = 35e-6    # copper thickness (m) — 1 oz default
    unit_str: str = "mm"           # display unit string
    out_mult: float = 1e3          # multiply SI → display unit

    @property
    def lambda0(self) -> float:
        return C_LIGHT / self.fr

    @property
    def k0(self) -> float:
        return 2 * np.pi / self.lambda0


_REGISTRY: dict[str, type["AntennaBase"]] = {}
_CATEGORIES: dict[str, list[str]] = {}


def register_antenna(name: str, category: str = "Other"):
    """Decorator — register an antenna so the UI picks it up."""
    def _wrap(cls):
        cls.name = name
        cls.category = category
        _REGISTRY[name] = cls
        _CATEGORIES.setdefault(category, []).append(name)
        return cls
    return _wrap


def available_antennas() -> dict[str, list[str]]:
    """Return {category: [names]} for building the UI."""
    return {c: sorted(names) for c, names in sorted(_CATEGORIES.items())}


def get_antenna(name: str) -> "AntennaBase":
    return _REGISTRY[name]()


class AntennaBase:
    """Override the methods below to add a new antenna."""
    name: str = ""
    category: str = ""
    description: str = ""
    notes: str = ""     # short physics note shown in the Info panel

    # --------- inputs ---------
    def inputs(self) -> list[Input]:
        """Extra inputs beyond the base ones (fr, er, Z0, h, Ls, Ws)."""
        return []

    # --------- math ---------
    def compute(self, ctx: Context, params: dict) -> dict:
        """Return a dict of results. All lengths in METERS in the dict."""
        raise NotImplementedError

    # --------- text summary ---------
    def summary(self, ctx: Context, results: dict) -> str:
        """Return a multi-line text summary with dimensions + impedances."""
        m = ctx.out_mult
        u = ctx.unit_str
        lines = [f"{self.name}  ({self.category})"]
        if self.notes:
            lines.append(self.notes)
        lines.append("")
        lines.append(f"  fr      = {ctx.fr/1e9:.4f} GHz")
        lines.append(f"  λ₀      = {ctx.lambda0 * m:.4f} {u}")
        lines.append(f"  εr      = {ctx.er:.3f}")
        lines.append(f"  h       = {ctx.h * m:.4f} {u}")
        lines.append("")
        lines.extend(self._summary_extra(ctx, results))
        return "\n".join(lines)

    def _summary_extra(self, ctx: Context, results: dict) -> list[str]:
        """Override to add antenna-specific summary lines. Pull from `results`."""
        m = ctx.out_mult
        u = ctx.unit_str
        out = []
        for k, v in results.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                # heuristic: small numbers probably in meters → convert
                if k in ("Z_edge", "Z_in", "Z_coax", "impedance"):
                    out.append(f"  {k:<8s}= {v:.2f} Ω")
                elif k in ("Er_eff", "Ereff", "efficiency", "directivity", "gain_dBi"):
                    out.append(f"  {k:<8s}= {v:.3f}")
                elif k in ("N", "turns"):
                    out.append(f"  {k:<8s}= {int(v)}")
                else:
                    out.append(f"  {k:<8s}= {v*m:.4f} {u}")
        return out

    # --------- plots ---------
    def plot_geometry(self, ax, ctx: Context, results: dict):
        """Matplotlib axis — draw top-down CAD-style view with dimensions.
        Coordinates should be in DISPLAY units (mm / mils), i.e., multiplied by ctx.out_mult.
        """
        ax.text(0.5, 0.5, "No geometry view implemented", ha="center", va="center",
                transform=ax.transAxes, color="#888", fontsize=12)
        ax.set_axis_off()

    def plot_fields(self, ax, ctx: Context, results: dict):
        """Matplotlib axis — E-field / current distribution."""
        ax.text(0.5, 0.5, "No field plot — see Radiation Pattern tab",
                ha="center", va="center", transform=ax.transAxes, color="#888", fontsize=12)
        ax.set_axis_off()

    # --------- radiation ---------
    def pattern(self, theta: np.ndarray, phi: np.ndarray,
                ctx: Context, results: dict) -> np.ndarray:
        """Return |U(θ,φ)| on the meshgrid. Override for each antenna.
        θ ∈ [0, π] (from +z axis). φ ∈ [0, 2π] (from +x axis, counter-clockwise).
        Shape should match the broadcast of theta and phi.
        """
        # Default: isotropic
        return np.ones_like(theta + phi)

    def pattern_cuts(self, ctx: Context, results: dict,
                     n: int = 721) -> dict:
        """Return a dict with elevation (E-plane, φ=0) and azimuth (H-plane, θ=π/2) cuts.
        Returns arrays in θ (elev) and φ (azim), each normalized to 1.
        """
        theta_e = np.linspace(0, 2 * np.pi, n)
        phi_e = np.zeros_like(theta_e)
        U_e = self.pattern(theta_e, phi_e, ctx, results)
        U_e = np.abs(U_e)
        if np.max(U_e) > 0:
            U_e /= np.max(U_e)

        phi_a = np.linspace(0, 2 * np.pi, n)
        theta_a = np.full_like(phi_a, np.pi / 2)
        U_a = self.pattern(theta_a, phi_a, ctx, results)
        U_a = np.abs(U_a)
        if np.max(U_a) > 0:
            U_a /= np.max(U_a)

        return {
            "theta_e": theta_e, "U_e": U_e,
            "phi_a": phi_a, "U_a": U_a,
        }

    def pattern_3d(self, ctx: Context, results: dict,
                   n_theta: int = 73, n_phi: int = 145,
                   log_scale: bool = False, floor_db: float = -30.0) -> tuple:
        """Return (X, Y, Z, magnitude) for a 3D polar surface."""
        theta = np.linspace(0, np.pi, n_theta)
        phi = np.linspace(0, 2 * np.pi, n_phi)
        TH, PH = np.meshgrid(theta, phi, indexing="ij")
        U = np.abs(self.pattern(TH, PH, ctx, results))
        if np.max(U) > 0:
            U = U / np.max(U)
        if log_scale:
            with np.errstate(divide="ignore"):
                Udb = 20 * np.log10(np.maximum(U, 1e-10))
            Udb = np.clip(Udb, floor_db, 0)
            R = (Udb - floor_db) / (-floor_db)   # 0..1
        else:
            R = U
        X = R * np.sin(TH) * np.cos(PH)
        Y = R * np.sin(TH) * np.sin(PH)
        Z = R * np.cos(TH)
        return X, Y, Z, U

    # --------- figures of merit ---------
    def figures_of_merit(self, ctx: Context, results: dict) -> dict:
        """Return FOM dict: directivity, HPBW (E/H), F/B, etc."""
        # Default: compute numerically from the radiation pattern.
        n_th, n_ph = 181, 361
        theta = np.linspace(0, np.pi, n_th)
        phi = np.linspace(0, 2 * np.pi, n_ph)
        TH, PH = np.meshgrid(theta, phi, indexing="ij")
        U = np.abs(self.pattern(TH, PH, ctx, results)) ** 2
        if np.max(U) == 0:
            return {}
        dth = theta[1] - theta[0]
        dph = phi[1] - phi[0]
        P_rad = np.sum(U * np.sin(TH)) * dth * dph
        D_max = 4 * np.pi * np.max(U) / P_rad if P_rad > 0 else np.nan

        # HPBW in E-plane (φ=0) and H-plane (θ=π/2)
        def hpbw(angle, Un):
            Un = Un / np.max(Un) if np.max(Un) > 0 else Un
            imax = np.argmax(Un)
            # find -3 dB points on either side (0.5 power = 0.707 amplitude)
            half = 0.5 * Un[imax]   # U is already magnitude², so use 0.5
            # this operates on |U|² so half-power = 0.5
            left = imax
            while left > 0 and Un[left] > half:
                left -= 1
            right = imax
            while right < len(Un) - 1 and Un[right] > half:
                right += 1
            return angle[right] - angle[left]

        U_E = np.abs(self.pattern(theta, np.zeros_like(theta), ctx, results)) ** 2
        U_H = np.abs(self.pattern(np.full_like(phi, np.pi/2), phi, ctx, results)) ** 2
        hpbw_E = np.degrees(hpbw(theta, U_E)) if np.max(U_E) > 0 else np.nan
        hpbw_H = np.degrees(hpbw(phi, U_H)) if np.max(U_H) > 0 else np.nan

        return {
            "Directivity_dBi": 10 * np.log10(D_max) if D_max > 0 else np.nan,
            "HPBW_E_deg": hpbw_E,
            "HPBW_H_deg": hpbw_H,
        }
