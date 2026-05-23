"""
Basic RF physics helpers and a small substrate library.

The substrate library has two layers:
  • BUILTIN_SUBSTRATES — hard-coded reference materials (read-only)
  • user library      — loaded from ~/.antenna_designer/substrates.json,
                        edited via the GUI's "Manage substrates…" dialog

`SUBSTRATES` is the merged view (built-ins + user). Call
`reload_user_substrates()` after editing the user library on disk to
refresh the merged dict in place.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

C_LIGHT = 2.99792458e8
MU0 = 4e-7 * np.pi
EPS0 = 8.8541878128e-12
ETA0 = np.sqrt(MU0 / EPS0)    # ≈ 376.73 Ω


# -------- Substrate library (Er, tan δ @ design freq, typical thicknesses mm) --
BUILTIN_SUBSTRATES = {
    "FR-4 (generic)":            {"er": 4.4, "tan_d": 0.02,    "thick_mm": [0.2, 0.4, 0.8, 1.0, 1.524, 1.6]},
    "FR-4 (low-loss Isola 370HR)":{"er": 4.24,"tan_d": 0.021,   "thick_mm": [0.254, 0.508, 0.787, 1.524]},
    "Rogers RO4003C":            {"er": 3.38,"tan_d": 0.0027,  "thick_mm": [0.203, 0.305, 0.508, 0.813, 1.524]},
    "Rogers RO4350B":            {"er": 3.48,"tan_d": 0.0037,  "thick_mm": [0.168, 0.254, 0.508, 0.762, 1.524]},
    "Rogers RO3003":             {"er": 3.00,"tan_d": 0.001,   "thick_mm": [0.127, 0.254, 0.508, 0.762, 1.524]},
    "Rogers RT/duroid 5880":     {"er": 2.20,"tan_d": 0.0009,  "thick_mm": [0.127, 0.254, 0.381, 0.508, 0.787]},
    "Rogers RT/duroid 6002":     {"er": 2.94,"tan_d": 0.0012,  "thick_mm": [0.127, 0.254, 0.508, 0.762]},
    "Taconic TLY-5":             {"er": 2.20,"tan_d": 0.0009,  "thick_mm": [0.127, 0.254, 0.508, 0.787]},
    "Isola I-Tera MT40":         {"er": 3.45,"tan_d": 0.0031,  "thick_mm": [0.127, 0.254, 0.508, 0.762]},
    "Polyimide (Kapton)":        {"er": 3.5, "tan_d": 0.005,   "thick_mm": [0.05, 0.1, 0.2]},
    "Alumina Al2O3 (99.5%)":     {"er": 9.9, "tan_d": 0.0001,  "thick_mm": [0.254, 0.635]},
    "Air / vacuum":              {"er": 1.0006, "tan_d": 0.0,  "thick_mm": [1.0, 5.0]},
    "Quartz fused":              {"er": 3.78,"tan_d": 0.0001,  "thick_mm": [0.254, 0.508]},
    "PTFE (generic)":            {"er": 2.10,"tan_d": 0.0004,  "thick_mm": [0.25, 0.5, 1.0]},
    "JLC Prepreg 7628":          {"er": 4.4, "tan_d": 0.02,    "thick_mm": [0.0912, 0.1842, 0.2799]},
}


# --- User substrate library (persists to disk) ------------------------------

USER_SUBSTRATES_PATH = Path.home() / ".antenna_designer" / "substrates.json"


def is_builtin_substrate(name: str) -> bool:
    """Return True if `name` is a built-in (read-only) substrate."""
    return name in BUILTIN_SUBSTRATES


def load_user_substrates() -> dict:
    """Load the user-added substrate dict from disk. Returns {} if missing
    or unparseable — never raises, so the GUI always starts up."""
    if not USER_SUBSTRATES_PATH.exists():
        return {}
    try:
        raw = json.loads(USER_SUBSTRATES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        try:
            er = float(entry.get("er", 0))
            tan_d = float(entry.get("tan_d", 0))
            thick = [float(t) for t in entry.get("thick_mm", []) if t]
            if er > 0:
                out[str(name)] = {"er": er, "tan_d": tan_d,
                                  "thick_mm": thick}
        except (TypeError, ValueError):
            continue
    return out


def save_user_substrates(user_dict: dict) -> None:
    """Write `user_dict` to disk. Creates the parent directory if needed."""
    USER_SUBSTRATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_SUBSTRATES_PATH.write_text(
        json.dumps(user_dict, indent=2, sort_keys=True),
        encoding="utf-8")


# Merged view consumed by the rest of the app. Built-ins come first so a
# user entry that happens to share a name overrides it.
SUBSTRATES = dict(BUILTIN_SUBSTRATES)
SUBSTRATES.update(load_user_substrates())


def reload_user_substrates() -> None:
    """Re-read the user library from disk and refresh SUBSTRATES in place.

    The merged dict is updated mutatively so any module that imported it
    via `from physics import SUBSTRATES` sees the new entries.
    """
    SUBSTRATES.clear()
    SUBSTRATES.update(BUILTIN_SUBSTRATES)
    SUBSTRATES.update(load_user_substrates())


def wavelength(freq_hz: float, er: float = 1.0) -> float:
    """Wavelength in a medium with relative permittivity er (m)."""
    return C_LIGHT / (freq_hz * np.sqrt(er))


def skin_depth(freq_hz: float, sigma: float = 5.8e7, mu_r: float = 1.0) -> float:
    """Skin depth (m). Copper conductivity ≈ 5.8×10⁷ S/m."""
    return 1.0 / np.sqrt(np.pi * freq_hz * MU0 * mu_r * sigma)


def return_loss_db(gamma_mag: float) -> float:
    if gamma_mag <= 0:
        return np.inf
    return -20 * np.log10(gamma_mag)


def vswr(gamma_mag: float) -> float:
    g = min(abs(gamma_mag), 0.999999)
    return (1 + g) / (1 - g)


def reflection_coeff(z_load: complex, z0: float = 50.0) -> complex:
    return (z_load - z0) / (z_load + z0)


def near_field_distance(largest_dim_m: float, freq_hz: float) -> dict:
    """Return reactive/radiating near-field and far-field boundaries."""
    lam = C_LIGHT / freq_hz
    D = largest_dim_m
    reactive = 0.62 * np.sqrt(D ** 3 / lam) if D > 0 else 0.0
    far = 2 * D ** 2 / lam if D > 0 else 0.0
    return {"reactive_m": reactive, "fresnel_start_m": reactive,
            "fraunhofer_start_m": far, "lambda_m": lam}
