# Elite Antenna Designer v2

PyQt6 replacement for the original `AntennaGUI.py`. Modular architecture, expanded antenna library, better plotting including 3D radiation patterns.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python antenna_designer.py
```

## Project layout

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

## Adding a new antenna

1. Create a class in the appropriate module inheriting `AntennaBase`.
2. Implement `inputs()`, `compute()`, `plot_geometry()`, `plot_fields()`, `pattern_3d()`.
3. Decorate with `@register_antenna("My Antenna", category="Category")`.
4. Import the module in `antennas/__init__.py`.

That's it — it shows up in the dropdown automatically.
