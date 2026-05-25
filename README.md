# Antenna Stuff

A small toolkit for hands-on antenna work. Two PyQt6 apps live side-by-side:

- **`antenna_designer/`** — interactive synthesis & analysis tool (the original `AntennaGUI.py` rebuilt into a modular PyQt6 app).
- **`vna_gui/`** — antenna-focused front-end for the LibreVNA hardware. Live S-parameter sweeps, Touchstone overlays, calibration wizard, image / Touchstone export, marker math.

Plus supporting goodies: `matlab_scripts/` (radiation-pattern & impedance utilities), `patch_analysis/`, `s_param_extract.py`, and a few CST/3D models.

---

## Antenna Designer

PyQt6 replacement for the original `AntennaGUI.py`. Modular architecture, expanded antenna library, better plotting including 3D radiation patterns.

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python antenna_designer.py
```

### Project layout

```
antenna_designer.py         # Entry point
antennas/
    base.py                 # AntennaBase ABC + @register_antenna decorator
    patch.py                # Rectangular (edge/rear), circular, PIFA, 2x1 array
    wire.py                 # Dipole, monopole, Yagi-Uda, LPDA
    aperture.py             # Slot, bowtie, Vivaldi, pyramidal horn
    helical_loop.py         # Axial-mode helical, small loop, resonant loop
    phased.py               # Linear phased array
calculators/
    microstrip.py           # Hammerstad-Jensen synthesis (any Z), analysis, Ereff
    cpw.py                  # CPW and CPWG (Wheeler/conformal mapping)
    coax.py                 # Coax impedance synthesis + analysis (any Z)
    stripline.py            # Balanced stripline
    matching.py             # Quarter-wave, single-stub, L-network
    physics.py              # Skin depth, wavelength, substrate library
plotting/
    cad.py                  # CAD-style dimension lines, leader lines, scale bars
    radiation3d.py          # 3D far-field pattern (pyqtgraph OpenGL)
ui/
    main_window.py          # Main QMainWindow + tabs + docks
    input_panel.py          # Dynamic input panel
    calculators_tab.py      # T-line calculators UI
```

### Adding a new antenna

1. Create a class in the appropriate module inheriting `AntennaBase`.
2. Implement `inputs()`, `compute()`, `plot_geometry()`, `plot_fields()`, `pattern_3d()`.
3. Decorate with `@register_antenna("My Antenna", category="Category")`.
4. Import the module in `antennas/__init__.py`.

That's it — it shows up in the dropdown automatically.

---

## VNA Tester (`vna_gui/`)

Antenna-focused measurement front-end for the **LibreVNA** hardware. Talks to the LibreVNA-GUI's SCPI server (TCP 19542). Designed to be portable — drop on a flash drive together with `LibreVNA/` and go.

### Run

```bash
cd vna_gui
python vna_tester.py
```

The app auto-launches `LibreVNA-GUI.exe` if it isn't already running. Use **Connection → Browse…** to point at your install if it can't find it on its own.

### Features

- **Live S₁₁ / S₁₂ / S₂₁ / S₂₂ sweeps** with selectable IF BW, averaging, points, power, start/stop or center/span.
- **Tile-able plot grid** — Cartesian (dual-axis, many Y formats: dB, VSWR, phase, group delay, R/X/|Z|, mismatch loss, …), Smith chart, polar, time-domain (TDR via windowed IFFT).
- **Touchstone overlays** — load any number of `.s1p` / `.s2p` files as static reference traces alongside the live sweep. **Load Touchstone…** defaults to the project's `s1p_s2p_files/` folder. **Clear refs** asks for confirmation and cleans up plot overlays + attached markers automatically.
- **Markers** — normal (draggable, free-form frequency entry like `2.4G`, `915M`, `1.575 GHz`), max, min, target-dB crossing, multi-resonance −10 dB bandwidth boxes. Right-click any marker for kind, scope, color, "also dot/read on traces" with **Select all / Clear all**, "show values on dots" with a dark fill behind the readout for legibility.
- **Sweep range pinning** — when you change the sweep, plots clamp the X axis to the new range so loaded references with a wider band don't keep the view zoomed out. Hit a panel's Reset button to autofit everything (refs included).
- **Calibration wizard** — Port-1 SOL, Port-2 SOL, Through, full SOLT. Save/Load `.cal` files (defaults to `vna_gui/cals/`). Loading a cal pulls its sweep grid back into the UI.
- **Antenna metrics** — resonance, S₁₁ min, VSWR, fractional bandwidth, impedance at resonance, Q. Live verdict ("Good / Marginal / Poor") tied to the marker's target-dB.
- **Image export** — three modes: per-panel re-render (sharp at any resolution), whole-window high-res composite (renders each panel individually then composites), and plain-screenshot upscale to the selected resolution. Smith / Polar plots correctly restore their on-screen size after exporting.
- **Session save/load** (`.json`) — sweep config, plot layout, custom band presets.
- **CSV log** — append antenna metrics every sweep.

### Project layout

```
vna_gui/
    vna_tester.py              # Entry point
    vna_tester/
        app.py                 # QApplication + dark theme bootstrap
        controller.py          # SCPI wrapper, sweep config, calibration
        worker.py              # Background sweep / cal-measure threads
        scpi.py                # Minimal SCPI socket client
        trace.py               # Trace + TraceManager + per-trace assignments
        markers.py             # Marker model + evaluators
        metrics.py             # Antenna metrics + verdict
        units.py               # Frequency parsing ("2.4G", "915M", …)
        paths.py               # Portable path discovery + config
        launcher.py            # LibreVNA-GUI auto-launch
        plots/
            base.py            # PlotPanel ABC, header buttons, helpers
            cartesian.py       # Dual-axis Cartesian, dB / VSWR / Z / Phase / GD / …
            smith.py           # Matplotlib Smith chart
            polar.py           # Matplotlib polar plot
            tdr.py             # Time-domain reflectometry (IFFT)
            grid.py            # Tile-able plot grid container
            export.py          # Image-export strategies
        ui/
            main_window.py     # Top-level QMainWindow
            connection_panel.py
            sweep_panel.py
            trace_panel.py
            marker_panel.py
            metrics_panel.py
            band_presets.py
            plot_config_dialog.py
            calibration_dialog.py
            export_dialog.py
    cals/                      # Saved calibrations (.cal)
    s1p_s2p_files/             # Saved & reference Touchstone files
    Images/                    # Default folder for exported images
    vna_tester_config.json     # Persisted UI / connection / preset state
```

### Keyboard shortcuts

| Key   | Action |
|-------|--------|
| Ctrl+S | Save current sweep as `.s2p` |
| Ctrl+E | Export image |
| F5    | Apply sweep settings to device |
| F6    | Single sweep |
| F8    | Open calibration wizard |

### Characterization tools

Long-running reliability / accuracy tests live in `vna_gui/tools/`.

```bash
cd vna_gui
python tools/characterization_gui.py
```

The characterization window configures repeated drift / repeatability runs,
stores one summary CSV plus raw Touchstone files, and can generate analysis
plots from the completed run. The same workflow is also available from the
command line via `python -m vna_tester.tools.characterize` and
`python -m vna_tester.tools.analyze_characterization`.
