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
class Curve:
    """A parametric curve in the antenna's local coordinate system.

    Antennas with non-rectangular geometry (Vivaldi taper, helical wire,
    spiral, horn flare) populate this so the summary can list the closed-form
    equation, and the "Export geometry" feature can dump either ready-to-paste
    CST analytical-curve text or whitespace-separated x y z TXT files for
    CST's Curve-from-File / spline import.

    All coordinates are SI (metres). The display layer converts to the user's
    current unit when rendering.

    `cst` — optional dict pre-formatted in the user's DISPLAY units with keys
    `x_t`, `y_t`, `z_t` (parametric expressions using 't'), `t_min`, `t_max`
    (numeric or string expression like '2*pi*N'), and `t_unit` (label only,
    e.g. 'mm' or 'rad'). When present the summary prints a block the user
    can copy directly into CST's "Create Analytical Curve" dialog.
    """
    name: str
    equation: str                                       # human-readable expr
    parameters: dict                                    # {sym: (value_si, unit_label)}
    points_m: list = field(default_factory=list)       # list of (x, y) or (x, y, z) tuples
    closed: bool = False                                # polyline closes back to start?
    note: str = ""                                      # optional extra context
    cst: Optional[dict] = None                          # CST analytical-curve form
    dxf_combined: bool = True                           # include in the single combined DXF?


@dataclass
class Input:
    """Description of one user input field for an antenna.

    If `choices` is given the UI renders a dropdown instead of a free-text
    field — use it for any input with a fixed set of valid values so the user
    cannot mistype it.
    """
    key: str
    label: str
    default: str
    unit: str = ""
    tooltip: str = ""
    choices: Optional[list[str]] = None


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

    # --------- unit helpers ---------------------------------------------------
    def m(self, val, default_m: float = 0.0) -> float:
        """Convert a display-unit value (float or string) to meters.

        Antenna-specific inputs are entered in the unit dropdown's current
        unit (mm or mils). Use this helper so a single call works in both
        modes — never hardcode `* 1e-3`, which only works in mm.
        """
        try:
            return float(val) / self.out_mult
        except (TypeError, ValueError):
            return default_m

    def m_or(self, val, default_m: float) -> float:
        """Like `m()` but treats a missing or non-positive entry as 'auto',
        returning the provided default (in meters). Useful for fields where
        the user types 0 (or leaves blank) to mean 'compute it for me'.
        """
        try:
            v = float(val)
        except (TypeError, ValueError):
            return default_m
        return default_m if v <= 0 else v / self.out_mult


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
    """Override the methods below to add a new antenna.

    Per-antenna metadata is exposed as class attributes so subclasses can
    declare polarization, the natural beam axis, and qualitative bandwidth
    properties in one line without having to override summary().
    """
    name: str = ""
    category: str = ""
    description: str = ""
    notes: str = ""     # short physics note shown in the Info panel

    # ---- universal antenna metadata ------------------------------------
    polarization: str = "linear"          # "linear / E along ..", "RHCP", "LHCP", "dual"
    beam_axis: str = "broadside (+Z)"     # "broadside (+Z)", "end-fire (+X)", "omni"
    bandwidth_note: str = "narrowband (resonant, ~2 %)"

    def bandwidth_estimate(self, ctx: "Context", results: dict) -> dict:
        """Return {f_low_hz, f_high_hz, fractional, note} for the operating band.

        Default is ±1 % around the design frequency (narrowband resonant).
        Wideband antennas (Vivaldi, LPDA, Bowtie) override this method or
        populate `results['bandwidth']` directly inside compute().
        """
        if "bandwidth" in results:
            return results["bandwidth"]
        return {"f_low_hz": ctx.fr * 0.99, "f_high_hz": ctx.fr * 1.01,
                "fractional": 0.02, "note": self.bandwidth_note}

    def largest_dim_m(self, results: dict) -> float:
        """Largest physical dimension — drives the Fraunhofer / Fresnel calc."""
        bb = results.get("board_size")
        if bb:
            return float(max(bb))
        return 0.0

    def _curves_for_export(self, ctx: "Context", results: dict) -> list:
        """Return the list of curves translated so the board centre is at
        the origin. Antennas opt in by populating `results['board_center_m']`
        with the (cx, cy) of the board centre in the antenna's NATIVE frame.
        If absent or (0, 0), curves pass through unchanged.
        """
        curves = results.get("curves") or []
        bc = results.get("board_center_m")
        if not bc:
            return curves
        cx, cy = bc
        return recenter_curves(curves, float(cx), float(cy), ctx)

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
        bb = results.get("board_size")
        if bb:
            lines.append("")
            lines.append("Board / substrate outline")
            lines.append(f"  Board length  (X) = {bb[0]*m:.2f} {u}")
            lines.append(f"  Board width   (Y) = {bb[1]*m:.2f} {u}")
            lines.append(f"  Board area        = {bb[0]*bb[1]*m*m:.1f} {u}²")

        # --- Universal antenna metadata --------------------------------
        bw = self.bandwidth_estimate(ctx, results)
        D = self.largest_dim_m(results)
        lam = ctx.lambda0
        lines.append("")
        lines.append("Operating envelope")
        lines.append(f"  Polarization    = {self.polarization}")
        lines.append(f"  Beam axis       = {self.beam_axis}")
        lines.append(f"  Bandwidth est.  = "
                     f"{bw['f_low_hz']/1e9:.2f} – {bw['f_high_hz']/1e9:.2f} GHz   "
                     f"(fractional {bw['fractional']*100:.1f} %)")
        if bw.get("note"):
            lines.append(f"                    [{bw['note']}]")
        if D > 0:
            d_reactive = 0.62 * np.sqrt(D ** 3 / lam) if D > 0 else 0
            d_far      = 2 * D ** 2 / lam if D > 0 else 0
            lines.append(f"  Largest dim D   = {D*m:.2f} {u}   "
                         f"(D/λ = {D/lam:.2f})")
            lines.append(f"  Far-field start = {d_far*m:.2f} {u}   "
                         f"(Fraunhofer 2D²/λ)")
            lines.append(f"  Radiating NF    = {d_reactive*m:.2f} {u}   "
                         f"(Fresnel 0.62·√(D³/λ))")

        # --- Substrate loss budget (where relevant) --------------------
        loss = self._loss_summary(ctx, results)
        if loss:
            lines.append("")
            lines.append("Loss estimate (resonant antennas)")
            lines.extend(loss)

        # --- Math equations (symbolic forms) ---------------------------
        math_eqs = results.get("math_equations") or []
        if math_eqs:
            lines.append("")
            lines.append("─" * 60)
            lines.append("Mathematical form  (closed-form geometry)")
            lines.append("─" * 60)
            for eq in math_eqs:
                # Each entry is either a (name, equation) tuple or a dict
                if isinstance(eq, dict):
                    name = eq.get("name", "")
                    expr = eq.get("equation", "")
                    note = eq.get("note", "")
                else:
                    name, expr = eq[0], eq[1]
                    note = eq[2] if len(eq) > 2 else ""
                if name:
                    lines.append(f"  • {name}")
                    lines.append(f"        {expr}")
                else:
                    lines.append(f"  • {expr}")
                if note:
                    lines.append(f"        ({note})")

        # --- CST PARAMETRIC RECIPE -------------------------------------
        cst_params = results.get("cst_parameters") or {}
        curves = self._curves_for_export(ctx, results)
        cst_curves = [c for c in curves if c.cst]
        if cst_params or cst_curves:
            lines.append("")
            lines.append("═" * 60)
            lines.append("CST PARAMETRIC RECIPE")
            lines.append("═" * 60)
            lines.append("  Tune the parameters below in CST and the whole")
            lines.append("  geometry re-meshes automatically — no need to")
            lines.append("  re-export every time you tweak a dimension.")
            lines.append("")

            if cst_params:
                lines.append("Step 1 — Modeling ▸ Parameter List   "
                             "(add these entries):")
                # Split into base (have value) vs derived (have formula)
                base = [(n, p) for n, p in cst_params.items()
                        if "formula" not in p]
                derived = [(n, p) for n, p in cst_params.items()
                           if "formula" in p]
                if base:
                    width = max(len(n) for n, _ in base) if base else 1
                    for n, p in base:
                        val = p["value"]
                        unit = p.get("unit", "")
                        comment = p.get("comment", "")
                        unit_str = f"[{unit}] " if unit else ""
                        lines.append(f"    {n:<{width}} = {val:<12.6g}  "
                                     f"; {unit_str}{comment}")
                if derived:
                    lines.append("")
                    lines.append("  Derived (paste each as a formula, not a value):")
                    width = max(len(n) for n, _ in derived) if derived else 1
                    for n, p in derived:
                        formula = p["formula"]
                        unit = p.get("unit", "")
                        comment = p.get("comment", "")
                        unit_str = f"[{unit}] " if unit else ""
                        # Show the computed value (if provided) as a sanity
                        # check alongside the formula.
                        val = p.get("value")
                        if isinstance(val, (int, float)):
                            value_str = f"   (= {val:.4g} {unit})" if unit else f"   (= {val:.4g})"
                        else:
                            value_str = ""
                        lines.append(f"    {n:<{width}} = {formula}{value_str}")
                        if comment:
                            lines.append(f"    {' '*width}   ; {comment}")

            if cst_curves:
                lines.append("")
                lines.append("Step 2 — Modeling ▸ Curves ▸ Create Analytical Curve")
                lines.append("  (create each curve below; the X(t)/Y(t)/Z(t)")
                lines.append("   expressions reference the parameters above):")
                for i, c in enumerate(cst_curves):
                    cst = c.cst
                    # Short, CST-friendly identifier from first word(s) of the name
                    cname = _short_cst_name(c.name)
                    lines.append("")
                    lines.append(f"  ► {c.name}")
                    lines.append(f"      Name:    {cname}")
                    lines.append(f"      X(t)  =  {cst['x_t']}")
                    lines.append(f"      Y(t)  =  {cst['y_t']}")
                    lines.append(f"      Z(t)  =  {cst['z_t']}")
                    tmin = cst['t_min']; tmax = cst['t_max']
                    if isinstance(tmin, (int, float)): tmin_s = f"{tmin:.6g}"
                    else: tmin_s = str(tmin)
                    if isinstance(tmax, (int, float)): tmax_s = f"{tmax:.6g}"
                    else: tmax_s = str(tmax)
                    lines.append(f"      Min(t) = {tmin_s}")
                    lines.append(f"      Max(t) = {tmax_s}    "
                                 f"(t in {cst.get('t_unit','rad')})")
                    if c.note:
                        lines.append(f"      • {c.note}")

            # Recipe footer — how to compose
            recipe = results.get("cst_recipe_steps")
            if recipe:
                lines.append("")
                lines.append("Step 3 — Compose:")
                for s in recipe:
                    lines.append(f"    {s}")

        # --- Sample-point footnote -------------------------------------
        bc = results.get("board_center_m") or (0.0, 0.0)
        if curves and any(c.points_m for c in curves):
            lines.append("")
            lines.append("DXF / spline export uses the board-centered frame")
            if abs(bc[0]) > 1e-12 or abs(bc[1]) > 1e-12:
                lines.append(f"  (shift Δx = {-bc[0]*m:.2f} {u}, "
                             f"Δy = {-bc[1]*m:.2f} {u} from CAD-tab coords).")
            lines.append(f"  The CST analytical expressions above use the "
                         f"antenna's NATIVE frame so the math matches the "
                         f"equations shown.")

        return "\n".join(lines)

    # --------- loss / efficiency hook -------------------------------------
    def _loss_summary(self, ctx: "Context", results: dict) -> list:
        """Return list of substrate-loss summary lines (or empty list).

        Default returns dielectric-loss-per-λg and a rough copper-loss
        contribution for any antenna that has a substrate (i.e. an `Ereff`
        in results). Override or return [] to suppress.
        """
        Ereff = results.get("Ereff") or results.get("Ereff_feed")
        if Ereff is None or ctx.h <= 0:
            return []
        # Approximate dielectric loss in dB/λg:
        #   α_d = (k0/2) · tan δ · (εr·(εr_eff−1)/((εr−1)·√εr_eff))   (Pozar 3.30)
        # Convert to per-λg loss.
        try:
            k0 = 2 * np.pi * ctx.fr / C_LIGHT
            ad = ((ctx.er * (Ereff - 1)) /
                  (max(ctx.er - 1, 1e-6) * np.sqrt(Ereff))) * (k0 * ctx.loss_tangent / 2)
            lam_g = ctx.lambda0 / np.sqrt(Ereff)
            db_per_lam_g = 8.685889638 * ad * lam_g
        except Exception:
            return []
        return [
            f"  ε_eff           = {Ereff:.3f}",
            f"  λ_g             = {lam_g*ctx.out_mult:.3f} {ctx.unit_str}",
            f"  Dielectric loss ≈ {db_per_lam_g:.3f} dB / λ_g   (tan δ = {ctx.loss_tangent:.4f})",
        ]

    # --------- export hook ------------------------------------------------
    def export_geometry_csv(self, ctx: "Context", results: dict) -> str:
        """Return a CSV string listing every parametric curve's sample points.

        Header per curve:  `# <name> -- <equation>` then one row per point as
        `curve_idx, point_idx, x_<unit>, y_<unit>[, z_<unit>]`. All values
        already converted to the user's display unit.
        """
        m = ctx.out_mult
        u = ctx.unit_str
        curves = self._curves_for_export(ctx, results)
        if not curves:
            return ("# No parametric curves declared by this antenna.\n"
                    "# (Open the Dimensions tab for rectangle-only geometry.)\n")
        out = [f"# antenna={self.name}    unit={u}    origin=board centre"]
        for i, c in enumerate(curves):
            out.append(f"# Curve {i}: {c.name}")
            out.append(f"#   {c.equation}")
            if c.parameters:
                pairs = []
                for sym, val in c.parameters.items():
                    if isinstance(val, tuple) and len(val) == 2:
                        v, unit = val
                        v_disp, unit_disp = _convert_curve_param(v, unit, ctx)
                        if isinstance(v_disp, tuple):
                            pairs.append(f"{sym} in [{v_disp[0]:.6g}, "
                                         f"{v_disp[1]:.6g}] {unit_disp}")
                        else:
                            pairs.append(f"{sym}={v_disp:.6g} {unit_disp}")
                    else:
                        pairs.append(f"{sym}={val!r}")
                out.append(f"#   where  " + ", ".join(pairs))
            dim = len(c.points_m[0]) if c.points_m else 2
            header = ["curve", "i", f"x_{u}", f"y_{u}"]
            if dim >= 3:
                header.append(f"z_{u}")
            out.append(",".join(header))
            for j, p in enumerate(c.points_m):
                row = [str(i), str(j), f"{p[0]*m:.6f}", f"{p[1]*m:.6f}"]
                if len(p) >= 3:
                    row.append(f"{p[2]*m:.6f}")
                out.append(",".join(row))
            if c.closed and c.points_m:
                p = c.points_m[0]
                row = [str(i), str(len(c.points_m)), f"{p[0]*m:.6f}", f"{p[1]*m:.6f}"]
                if len(p) >= 3:
                    row.append(f"{p[2]*m:.6f}")
                out.append(",".join(row))
        return "\n".join(out) + "\n"

    def export_cst_analytical_text(self, ctx: "Context", results: dict) -> str:
        """Return a complete CST recipe: parameter list + analytical curves.

        The output is ASCII-only and laid out so the user can paste each
        block into CST's Parameter List and Create-Analytical-Curve dialogs.
        Expressions are SYMBOLIC — they reference the parameter names so
        retuning the antenna only requires editing the parameter list.
        """
        u = ctx.unit_str
        curves = self._curves_for_export(ctx, results)
        cst_curves = [c for c in curves if c.cst]
        cst_params = results.get("cst_parameters") or {}
        if not cst_curves and not cst_params:
            return ("# No CST parametric recipe available for this antenna.\n"
                    "# Use the DXF exporter instead.\n")

        out = []
        out.append(f"# === CST PARAMETRIC RECIPE — {self.name} ===")
        out.append(f"# Coordinate unit: {u}    Frame: antenna native "
                   f"(translate in CST after building, if desired).")
        out.append("#")
        out.append("# Workflow:")
        out.append("#   1. Modeling > Parameter List: add the parameters below.")
        out.append("#   2. Modeling > Curves > Create Analytical Curve: build each curve.")
        out.append("#   3. Join Curves / Cover Curve / Boolean as needed.")
        out.append("")

        # ------- Parameter list -------
        if cst_params:
            base = [(n, p) for n, p in cst_params.items() if "formula" not in p]
            derived = [(n, p) for n, p in cst_params.items() if "formula" in p]
            out.append("# --- Parameters (base) ---")
            if base:
                width = max(len(n) for n, _ in base)
                for n, p in base:
                    val = p["value"]
                    unit = p.get("unit", "")
                    comment = p.get("comment", "")
                    unit_str = f"[{unit}] " if unit else ""
                    out.append(f"{n:<{width}} = {val:<12.6g}  ; {unit_str}{comment}")
            if derived:
                out.append("")
                out.append("# --- Parameters (derived — paste as formula) ---")
                width = max(len(n) for n, _ in derived)
                for n, p in derived:
                    formula = p["formula"]
                    unit = p.get("unit", "")
                    comment = p.get("comment", "")
                    unit_str = f"[{unit}] " if unit else ""
                    val = p.get("value")
                    val_str = (f"   ; computed = {val:.6g} {unit}".rstrip()
                               if isinstance(val, (int, float)) else "")
                    out.append(f"{n:<{width}} = {formula}{val_str}")
                    if comment:
                        out.append(f"{' '*width}    ; {comment}")
            out.append("")

        # ------- Analytical curves -------
        if cst_curves:
            out.append("# --- Analytical curves ---")
            for i, c in enumerate(cst_curves):
                cst = c.cst
                cname = _short_cst_name(c.name)
                tmin = cst['t_min']; tmax = cst['t_max']
                tmin_s = f"{tmin:.6g}" if isinstance(tmin, (int, float)) else str(tmin)
                tmax_s = f"{tmax:.6g}" if isinstance(tmax, (int, float)) else str(tmax)
                out.append("")
                out.append(f"# Curve {i+1}: {c.name}")
                out.append(f"#   {c.equation}")
                out.append(f"Name:    {cname}")
                out.append(f"X(t) =   {cst['x_t']}")
                out.append(f"Y(t) =   {cst['y_t']}")
                out.append(f"Z(t) =   {cst['z_t']}")
                out.append(f"Min(t) = {tmin_s}")
                out.append(f"Max(t) = {tmax_s}    "
                           f"; t in {cst.get('t_unit','rad')}")
                if c.note:
                    out.append(f"# Note: {c.note}")

        # ------- Compose-step recipe -------
        recipe = results.get("cst_recipe_steps")
        if recipe:
            out.append("")
            out.append("# --- Step 3: Compose ---")
            for s in recipe:
                out.append(f"#   {s}")
        out.append("")
        return "\n".join(out) + "\n"

    def export_spline_txt(self, ctx: "Context", results: dict,
                          curve_index: Optional[int] = None,
                          include_header: bool = False) -> str:
        """Return whitespace-separated x y z lines for CST's Curve-from-File.

        CST's importer is finicky about non-ASCII characters and many versions
        reject any comment lines at all, so by default we emit ONLY numeric
        rows — pure 'x y z' triples. Pass `include_header=True` (and accept
        the risk) if you want the antenna name and curve description in the
        file's leading comments.

        Coordinates are already in the user's display unit. Z is included as
        0 for 2-D curves so the file is uniformly 3-column (some CAD tools
        require it).
        """
        m = ctx.out_mult
        u = ctx.unit_str
        curves = self._curves_for_export(ctx, results)
        if curve_index is not None:
            if curve_index < 0 or curve_index >= len(curves):
                return ""
            curves = [curves[curve_index]]
        if not curves:
            return ""

        out = []
        if include_header:
            out.append(f"# antenna={self.name}  unit={u}  origin=board_centre")
            out.append("# format: x y z (whitespace separated)")
            out.append("")

        for ci, c in enumerate(curves):
            if not c.points_m:
                continue
            if include_header:
                # Plain ASCII only — CST rejects unicode in TXT comments.
                safe_name = "".join(
                    ch if ord(ch) < 128 else "_" for ch in c.name)
                out.append(f"# curve_{ci}: {safe_name}")
            for p in c.points_m:
                if len(p) == 2:
                    out.append(f"{p[0]*m:.6f} {p[1]*m:.6f} 0.000000")
                else:
                    out.append(f"{p[0]*m:.6f} {p[1]*m:.6f} {p[2]*m:.6f}")
            if c.closed:
                p = c.points_m[0]
                if len(p) == 2:
                    out.append(f"{p[0]*m:.6f} {p[1]*m:.6f} 0.000000")
                else:
                    out.append(f"{p[0]*m:.6f} {p[1]*m:.6f} {p[2]*m:.6f}")
            # Blank line between curves so a multi-curve file is at least
            # human-readable. Single-curve exports won't trigger this.
            if len(curves) > 1:
                out.append("")
        return "\n".join(out) + "\n"

    def export_combined_dxf(self, ctx: "Context", results: dict,
                            include_board_outline: bool = True) -> str:
        """Return a single DXF text containing every PRIMARY curve as its own
        polyline plus an optional board-outline rectangle for reference.

        Curves with `dxf_combined=False` are excluded (they're components of
        a closed curve also present). This is the recommended export for
        CST: one import, no redundant overlapping lines.
        """
        curves = [c for c in self._curves_for_export(ctx, results)
                  if c.dxf_combined]
        if include_board_outline and results.get("board_size"):
            bx, by = results["board_size"]
            outline_pts = [
                (-bx/2, -by/2), ( bx/2, -by/2),
                ( bx/2,  by/2), (-bx/2,  by/2),
            ]
            curves.append(Curve(
                name="Board outline (substrate envelope)",
                equation="board rectangle",
                parameters={"W": (bx, "m"), "L": (by, "m")},
                points_m=outline_pts, closed=True,
            ))

        lines = _dxf_header(ctx)
        lines += ["0", "SECTION", "2", "ENTITIES"]
        for ci, c in enumerate(curves):
            if not c.points_m:
                continue
            layer = f"curve_{ci:02d}"
            lines += _dxf_curve_block(c, layer, ctx)
        lines += ["0", "ENDSEC", "0", "EOF"]
        return "\r\n".join(lines) + "\r\n"

    def export_dxf_per_curve(self, ctx: "Context", results: dict) -> list:
        """Return list of (filename, content) tuples — one DXF file per curve.

        DXF is the standard CAD interchange format. Every CST version imports
        it natively via Curves → Curve → New Curve → Import (DXF), and the
        importer is far more tolerant of geometry than the spline-from-TXT
        path. Use this when the TXT import says 'No valid entries found.'
        """
        curves = self._curves_for_export(ctx, results)
        slug = "".join(
            ch.lower() if (ch.isalnum() or ch in "_-") else "_"
            for ch in self.name).strip("_")
        files = []
        for ci, c in enumerate(curves):
            if not c.points_m:
                continue
            cslug = "".join(
                ch.lower() if (ch.isalnum() or ch in "_-") else "_"
                for ch in c.name).strip("_")[:40]
            filename = f"{slug}_{ci:02d}_{cslug}.dxf"
            files.append((filename, _dxf_for_curve(c, ctx)))
        return files

    def export_spline_txt_per_curve(self, ctx: "Context", results: dict
                                    ) -> list:
        """Return list of (filename, content) tuples — one ASCII-pure TXT
        file per curve, ready to drop into CST's 'Curve from File' importer.

        Filenames use only ASCII, lower case, no spaces, suitable for any
        filesystem. Each file contains only numeric rows.
        """
        curves = self._curves_for_export(ctx, results)
        slug = "".join(
            ch.lower() if (ch.isalnum() or ch in "_-") else "_"
            for ch in self.name).strip("_")
        files = []
        for ci, c in enumerate(curves):
            if not c.points_m:
                continue
            cslug = "".join(
                ch.lower() if (ch.isalnum() or ch in "_-") else "_"
                for ch in c.name).strip("_")[:40]
            filename = f"{slug}_{ci:02d}_{cslug}.txt"
            content = self.export_spline_txt(
                ctx, results, curve_index=ci, include_header=False)
            files.append((filename, content))
        return files

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

    # --------- compact orientation overview ---------
    def plot_outline_overview(self, ax, ctx: "Context", results: dict):
        """Lightweight top-down outline + beam-direction arrow.

        Used by the 2D pattern tab's geometry overlay: the full `plot_geometry`
        view has dimension labels that turn into illegible noise at small size,
        so this stripped view shows just the board outline, the +X/+Y axes,
        and an arrow pointing along the antenna's main beam direction (or a
        marker if the beam points out of the page).
        """
        # Lazy imports — base.py shouldn't depend on plotting at import time.
        from matplotlib import patches as mpatches
        from plotting.cad import LAYER_COLORS, style_ax

        m = ctx.out_mult
        bb = results.get("board_size")
        if bb:
            x_ext = bb[0] * m
            y_ext = bb[1] * m
        else:
            x_ext = ctx.lambda0 * m
            y_ext = 0.5 * ctx.lambda0 * m
        if x_ext <= 0 or y_ext <= 0:
            return

        style_ax(ax.figure, ax,
                 "Antenna outline (top view) + beam direction",
                 equal=True, grid=False)
        ax.set_aspect("equal", adjustable="box")

        # Board / substrate footprint
        ax.add_patch(mpatches.Rectangle(
            (-x_ext / 2, -y_ext / 2), x_ext, y_ext,
            facecolor=LAYER_COLORS["substrate"],
            edgecolor=LAYER_COLORS["copper_edge"], lw=1.2, zorder=1))

        # Find the beam direction from a coarse pattern scan
        try:
            theta = np.linspace(0, np.pi, 49)
            phi = np.linspace(0, 2 * np.pi, 97)
            TH, PH = np.meshgrid(theta, phi, indexing="ij")
            U = np.abs(self.pattern(TH, PH, ctx, results))
            if U.max() > 0:
                ipk = np.unravel_index(np.argmax(U), U.shape)
                th_pk, ph_pk = float(theta[ipk[0]]), float(phi[ipk[1]])
            else:
                th_pk, ph_pk = 0.0, 0.0
        except Exception:
            th_pk, ph_pk = 0.0, 0.0

        # XY-plane projection of the beam: sinθ·(cosφ, sinφ).
        elev = float(np.sin(th_pk))
        ref_radius = 0.45 * max(x_ext, y_ext)

        beam_color = LAYER_COLORS["dim"]
        if elev < 0.30:
            # Beam mostly out of the page (broadside)
            ax.scatter([0], [0], s=160, facecolor="none",
                       edgecolor=beam_color, lw=2.0, zorder=6)
            ax.scatter([0], [0], s=20, color=beam_color, zorder=7)
            ax.text(0, y_ext * 0.35, "Beam → out of page (+Z)",
                    color=beam_color, fontsize=10,
                    ha="center", va="center", zorder=8,
                    bbox=dict(facecolor=LAYER_COLORS["bg"],
                              edgecolor=beam_color, alpha=0.7, pad=4))
        else:
            bx = ref_radius * np.cos(ph_pk)
            by = ref_radius * np.sin(ph_pk)
            ax.annotate("",
                        xy=(bx, by), xytext=(0, 0),
                        arrowprops=dict(arrowstyle="->",
                                         color=beam_color, lw=2.5),
                        zorder=6)
            ax.text(bx * 1.12, by * 1.12, "beam",
                    color=beam_color, fontsize=10,
                    ha="left" if bx >= -1e-9 else "right",
                    va="bottom" if by >= -1e-9 else "top", zorder=7)

        # +X / +Y axis indicators
        ax.annotate("", xy=(x_ext * 0.42, -y_ext * 0.42),
                    xytext=(0, -y_ext * 0.42),
                    arrowprops=dict(arrowstyle="->", color="#ff8888", lw=1.4))
        ax.text(x_ext * 0.43, -y_ext * 0.42, " +X",
                color="#ff8888", fontsize=9, ha="left", va="center")
        ax.annotate("", xy=(-x_ext * 0.42, y_ext * 0.42),
                    xytext=(-x_ext * 0.42, 0),
                    arrowprops=dict(arrowstyle="->", color="#88dd88", lw=1.4))
        ax.text(-x_ext * 0.42, y_ext * 0.45, "+Y",
                color="#88dd88", fontsize=9, ha="center", va="bottom")
        ax.margins(0.20)

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

        # HPBW from the full 2π principal-plane cuts. Using the periodic cut
        # (rather than a 0..π sweep) keeps the −3 dB search correct even when
        # the beam peak sits at θ=0 — e.g. broadside patches.
        cuts = self.pattern_cuts(ctx, results)
        hpbw_E = _hpbw_from_cut(cuts["theta_e"], cuts["U_e"])
        hpbw_H = _hpbw_from_cut(cuts["phi_a"], cuts["U_a"])

        return {
            "Directivity_dBi": 10 * np.log10(D_max) if D_max > 0 else np.nan,
            "HPBW_E_deg": hpbw_E,
            "HPBW_H_deg": hpbw_H,
        }


def _dxf_header(ctx: "Context") -> list:
    """Return the SECTION/HEADER/ENDSEC group-code lines."""
    return ["0", "SECTION",
            "2", "HEADER",
            "9", "$ACADVER", "1", "AC1015",            # AutoCAD R2000
            "9", "$INSUNITS", "70",
            "4" if ctx.unit_str == "mm" else "1",       # 4=mm, 1=inch
            "0", "ENDSEC"]


def _dxf_lwpolyline_block(curve: "Curve", layer: str, ctx: "Context") -> list:
    """LWPOLYLINE block for a 2-D curve. No dummy elevation point — that's
    the artifact that was making CST draw straight lines back to (0, 0).
    """
    m = ctx.out_mult
    pts = curve.points_m
    flag = 1 if curve.closed else 0
    lines = ["0", "LWPOLYLINE",
             "8", layer,
             "90", str(len(pts)),
             "70", str(flag)]
    for p in pts:
        lines += ["10", f"{p[0]*m:.6f}",
                  "20", f"{p[1]*m:.6f}"]
    return lines


def _dxf_polyline3d_block(curve: "Curve", layer: str, ctx: "Context") -> list:
    """3-D POLYLINE/VERTEX/SEQEND block (LWPOLYLINE is 2-D only)."""
    m = ctx.out_mult
    pts = curve.points_m
    closed_flag = 1 if curve.closed else 0
    poly_flag = 8 + closed_flag                          # 3D polyline
    vertex_flag = 32                                     # 3D vertex
    lines = ["0", "POLYLINE",
             "8", layer,
             "66", "1",
             "70", str(poly_flag),
             "10", "0.0", "20", "0.0", "30", "0.0"]
    for p in pts:
        x = p[0] * m
        y = p[1] * m
        z = (p[2] * m) if len(p) > 2 else 0.0
        lines += ["0", "VERTEX",
                  "8", layer,
                  "10", f"{x:.6f}",
                  "20", f"{y:.6f}",
                  "30", f"{z:.6f}",
                  "70", str(vertex_flag)]
    lines += ["0", "SEQEND", "8", layer]
    return lines


def _dxf_curve_block(curve: "Curve", layer: str, ctx: "Context") -> list:
    """Pick LWPOLYLINE (2-D) or POLYLINE (3-D) based on the points."""
    if any(len(p) > 2 for p in curve.points_m):
        return _dxf_polyline3d_block(curve, layer, ctx)
    return _dxf_lwpolyline_block(curve, layer, ctx)


def _dxf_for_curve(curve: "Curve", ctx: "Context") -> str:
    """Return a complete DXF text representing one Curve."""
    if not curve.points_m:
        return ""
    lines = _dxf_header(ctx)
    lines += ["0", "SECTION", "2", "ENTITIES"]
    lines += _dxf_curve_block(curve, "0", ctx)
    lines += ["0", "ENDSEC", "0", "EOF"]
    return "\r\n".join(lines) + "\r\n"


def _short_cst_name(name: str) -> str:
    """Compact identifier for a Curve.name — used as the CST analytical
    curve's Name field. Strips punctuation and parentheticals so the
    identifier stays short and valid.
    """
    # Drop everything in parentheses (mostly subtitles like "(closes the …)")
    base = name.split("(")[0]
    base = base.strip()
    # Drop common boilerplate words
    for drop in (" edge ", " edges ", " circle ", " arc "):
        base = base.replace(drop, " ")
    # Collapse to ASCII identifier
    cleaned = "".join(ch if (ch.isalnum() or ch == " ") else " "
                      for ch in base)
    parts = [p for p in cleaned.split() if p]
    name = "_".join(parts).lower()
    return name[:32] or "curve"


def recenter_curves(curves: list, cx_m: float, cy_m: float,
                    ctx: "Context") -> list:
    """Return new `Curve` objects with their POINT lists translated so
    (cx_m, cy_m) becomes the origin.

    Only `points_m` is shifted; the symbolic `cst` analytical-curve
    expressions are deliberately left in the antenna's native frame so the
    math matches the equations shown in the summary. Discrete DXF/spline
    exports use the centred points; the CST parametric recipe uses native
    symbols (the user can translate the assembly later in CST if needed).
    """
    if abs(cx_m) < 1e-12 and abs(cy_m) < 1e-12:
        return curves
    out = []
    for c in curves:
        new_points = []
        for p in c.points_m:
            if len(p) == 2:
                new_points.append((p[0] - cx_m, p[1] - cy_m))
            else:
                new_points.append((p[0] - cx_m, p[1] - cy_m, p[2]))
        out.append(Curve(
            name=c.name, equation=c.equation, parameters=c.parameters,
            points_m=new_points, closed=c.closed, note=c.note,
            cst=c.cst,                                  # native-frame symbols
            dxf_combined=c.dxf_combined,
        ))
    return out


def _convert_curve_param(value, unit_label: str, ctx: "Context"):
    """Convert a parameter value declared in SI (m, 1/m, m/rad, …) to the
    user's currently-selected display unit. Returns (value_or_tuple, label).
    Unrecognised units pass through unchanged.
    """
    u = ctx.unit_str
    m = ctx.out_mult
    if unit_label == "m":
        if isinstance(value, tuple):
            return (tuple(v * m for v in value), u)
        return (value * m, u)
    if unit_label == "1/m":
        if isinstance(value, tuple):
            return (tuple(v / m for v in value), f"1/{u}")
        return (value / m, f"1/{u}")
    if unit_label.startswith("m/"):
        suffix = unit_label[2:]
        if isinstance(value, tuple):
            return (tuple(v * m for v in value), f"{u}/{suffix}")
        return (value * m, f"{u}/{suffix}")
    if unit_label.startswith("m  "):
        # e.g. "m  (loop radius)" — preserve note after conversion
        note = unit_label[3:]
        if isinstance(value, tuple):
            return (tuple(v * m for v in value), f"{u}  {note}")
        return (value * m, f"{u}  {note}")
    return (value, unit_label)


def _hpbw_from_cut(angle: np.ndarray, U: np.ndarray) -> float:
    """Half-power beamwidth (deg) from one periodic principal-plane cut.

    `angle` spans a full 2π turn and `U` is the (amplitude) pattern on it.
    The −3 dB search wraps around the array so a peak at either end is handled
    correctly. Returns NaN if the pattern never drops 3 dB (omnidirectional).
    """
    U = np.abs(np.asarray(U, dtype=float))
    n = len(U)
    if n < 3 or U.max() <= 0:
        return float("nan")
    Un = U / U.max()
    imax = int(np.argmax(Un))
    half = 1.0 / np.sqrt(2.0)        # −3 dB in amplitude
    steps_l = 0
    while steps_l < n and Un[(imax - steps_l - 1) % n] > half:
        steps_l += 1
    steps_r = 0
    while steps_r < n and Un[(imax + steps_r + 1) % n] > half:
        steps_r += 1
    if steps_l + steps_r >= n - 1:
        return float("nan")          # never crosses −3 dB
    dang = (angle[-1] - angle[0]) / (n - 1)
    return float(np.degrees((steps_l + steps_r) * dang))
