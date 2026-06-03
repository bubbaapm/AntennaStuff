# Radar VNA Workbench

PyQt6 + PyQtGraph desktop GUI for LiteVNA / NanoVNA radar experiments.

## Run

```bash
pip install -r radar_gui/requirements.txt
python radar_gui/radar_gui.py
```

## What It Does

- Talks to LiteVNA / NanoVNA V2 with custom binary register/FIFO commands.
- Talks to classic NanoVNA shell devices with `sweep`, `frequencies`, `data 0`, and `data 1`.
- Processes S21 as a two-antenna stepped-frequency radar range profile.
- Shows live A-scope, waterfall, peak table, peak history, VNA verification plots, and DSP intermediate plots.
- Keeps VNA sweep points separate from A-scope interpolation bins.
- Saves and loads complex background profiles.
- Saves and replays raw complex capture sessions with peak history.

## Layout

- `models.py`: typed shared dataclasses.
- `device_backends.py`: serial protocol implementations and packet parsers.
- `vna_worker.py`: Qt worker that owns device polling.
- `radar_dsp.py`: pure NumPy/SciPy processing.
- `storage.py`: settings, background, and capture persistence.
- `ui_panels.py`: left-side control panels.
- `plots.py`: PyQtGraph plot widgets.
- `main_window.py`: top-level orchestration.
- `radar_gui.py`: folder-local entry point.
