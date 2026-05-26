# LibreVNA Characterization Tools

These tools are for reliability and accuracy characterization runs that are
longer or more report-oriented than normal interactive GUI use.

## Launch The Tool Window

From `vna_gui`:

```powershell
python tools\characterization_gui.py
```

The tool window starts the measurement logger in a child process, streams its
output, and can run the analyzer after the measurement finishes.

Use `Read From VNA` after loading or creating a calibration in the normal GUI
if you want the characterization run to use the exact active sweep grid.

For Raspberry Pi overnight setup, run this from `vna_gui`:

```bash
bash tools/setup_pi.sh
```

That script installs the Pi packages, LibreVNA udev rule, LibreVNA-GUI Raspberry
Pi release under `tools/librevna`, and the Python virtual environment. For the
manual equivalent and troubleshooting notes, see `PI_SETUP.md`.

For a prompted terminal workflow instead of remembering all CLI flags:

```bash
python tools/characterization_prompt.py
```

At the end of the prompted run, choose whether to generate analysis plots
immediately. To analyze an existing run later:

```bash
python tools/analyze_run.py
```

## Run From The Command Line

Dry run with a 50 ohm load:

```powershell
python -m vna_tester.tools.characterize --dut "50 ohm load dry run" --kind load --start 2.3e9 --stop 2.6e9 --points 1001 --ifbw 1000 --averaging 4 --interval 30 --count 10 --out characterization_runs\load_dry_run
```

If LibreVNA-GUI is not already running, the logger searches common locations
such as `tools/librevna` and `~/librevna`, then starts it automatically. If you
put the executable somewhere unusual, add:

```powershell
--librevna-gui C:\path\to\LibreVNA-GUI.exe
```

To load the newest copied calibration and use its sweep grid:

```powershell
--calibration latest --use-cal-sweep
```

Overnight antenna drift example:

```powershell
python -m vna_tester.tools.characterize --dut "Patch antenna overnight" --kind antenna --start 2.3e9 --stop 2.6e9 --points 1601 --ifbw 1000 --averaging 8 --interval 300 --duration 28800 --out characterization_runs\patch_overnight
```

Two-port thru/cable check:

```powershell
python -m vna_tester.tools.characterize --dut "Thru cable" --kind thru --start 100e6 --stop 6e9 --points 1001 --traces S11,S21,S12,S22 --interval 10 --count 30 --out characterization_runs\thru_repeatability
```

Analyze a run:

```powershell
python -m vna_tester.tools.analyze_characterization characterization_runs\patch_overnight
```

Or use the prompted wrapper:

```powershell
python tools\analyze_run.py
```

## Output Files

Each run folder contains:

- `summary.csv`: one row per sweep with drift, antenna, and control metrics.
- `temp_1_C`, `temp_2_C`, `temp_3_C`: parsed LibreVNA temperature readings when reported by the device.
- `metadata.json`: DUT name, notes, sweep settings, traces, calibration note, and device ID.
- `raw/`: one Touchstone file per sweep.
- `analysis/`: generated plots, temperature plots, and `analysis_report.md` after running the analyzer.

## Suggested Test Flow

1. Calibrate in the normal VNA GUI at the cable end.
2. Run a short 50 ohm load dry run.
3. Run a short antenna drift run to verify the span catches the resonance.
4. Run the longer antenna drift test.
5. Repeat with the load/open/short controls so antenna movement can be separated from VNA/cable drift.

## Schedule Fields

- `Interval s`: seconds between saved sweeps.
- `Count`: number of sweeps to save. If this is greater than zero, it takes priority.
- `Duration s`: total run time, used only when `Count` is zero.
- `Sweep timeout s`: maximum time allowed for one sweep to finish before the run reports an error.
- `Bandwidth target dB`: analysis threshold for bandwidth, usually `-10`. It does not change the VNA measurement.
