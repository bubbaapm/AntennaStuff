"""Analyze LibreVNA characterization runs produced by characterize.py."""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def _as_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def load_summary(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def elapsed_hours(rows: List[Dict[str, str]]) -> np.ndarray:
    values = np.asarray([_as_float(row.get("elapsed_s", "")) for row in rows], dtype=float)
    if np.all(~np.isfinite(values)):
        stamps = []
        for row in rows:
            raw = row.get("timestamp_utc", "").replace("Z", "+00:00")
            try:
                stamps.append(datetime.fromisoformat(raw).timestamp())
            except ValueError:
                stamps.append(float("nan"))
        values = np.asarray(stamps, dtype=float)
        values = values - np.nanmin(values)
    return values / 3600.0


def column(rows: List[Dict[str, str]], name: str) -> np.ndarray:
    return np.asarray([_as_float(row.get(name, "")) for row in rows], dtype=float)


def finite_xy(x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def save_line_plot(
    out: Path,
    x: np.ndarray,
    y: np.ndarray,
    title: str,
    ylabel: str,
    filename: str,
    marker: str = "o",
    y_scale: float = 1.0,
) -> bool:
    x, y = finite_xy(x, y)
    if x.size == 0:
        return False
    y = y * y_scale
    fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    ax.plot(x, y, marker=marker, linewidth=1.7, markersize=4)
    ax.set_title(title)
    ax.set_xlabel("Elapsed time (hours)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.28)
    fig.savefig(out / filename, dpi=160)
    plt.close(fig)
    return True


def parse_touchstone(path: Path) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    rows: List[List[float]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.split("!", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            values = [float(part) for part in line.split()]
            rows.append(values)
    if not rows:
        return {}
    arr = np.asarray(rows, dtype=float)
    freq = arr[:, 0]
    n_complex = (arr.shape[1] - 1) // 2
    data = [arr[:, 1 + 2 * i] + 1j * arr[:, 2 + 2 * i] for i in range(n_complex)]
    if n_complex == 1:
        return {"S11": (freq, data[0])}
    if n_complex >= 4:
        return {
            "S11": (freq, data[0]),
            "S21": (freq, data[1]),
            "S12": (freq, data[2]),
            "S22": (freq, data[3]),
        }
    return {f"S{i + 1}": (freq, data[i]) for i in range(n_complex)}


def first_raw_file(run_dir: Path, row: Dict[str, str]) -> Path | None:
    raw = row.get("raw_files", "")
    first = next((part for part in raw.split(";") if part), "")
    if not first:
        return None
    path = run_dir / first
    return path if path.exists() else None


def save_trace_overlay(run_dir: Path, out: Path, rows: List[Dict[str, str]]) -> bool:
    candidates = [rows[0], rows[len(rows) // 2], rows[-1]]
    labels = ["first", "middle", "last"]
    fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    plotted = False
    for label, row in zip(labels, candidates):
        path = first_raw_file(run_dir, row)
        if path is None:
            continue
        traces = parse_touchstone(path)
        if "S11" not in traces:
            continue
        freq, values = traces["S11"]
        db = 20.0 * np.log10(np.maximum(np.abs(values), 1e-12))
        ax.plot(freq / 1e9, db, linewidth=1.5, label=f"{label}: {path.name}")
        plotted = True
    if not plotted:
        plt.close(fig)
        return False
    ax.set_title("S11 Trace Overlay")
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("S11 (dB)")
    ax.grid(True, alpha=0.28)
    ax.legend(fontsize=8)
    fig.savefig(out / "trace_overlay_s11.png", dpi=160)
    plt.close(fig)
    return True


def save_histogram(out: Path, values: np.ndarray, title: str, xlabel: str, filename: str) -> bool:
    values = values[np.isfinite(values)]
    if values.size < 2:
        return False
    fig, ax = plt.subplots(figsize=(7, 4.8), constrained_layout=True)
    ax.hist(values, bins=min(20, max(5, int(math.sqrt(values.size)))), edgecolor="black", alpha=0.75)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")
    ax.grid(True, axis="y", alpha=0.25)
    fig.savefig(out / filename, dpi=160)
    plt.close(fig)
    return True


def write_report(out: Path, rows: List[Dict[str, str]], made: List[str]) -> None:
    f_res = column(rows, "f_res_Hz")
    s11_min = column(rows, "S11_min_dB")
    lines = [
        "# LibreVNA Characterization Analysis",
        "",
        f"Sweeps analyzed: {len(rows)}",
    ]
    if np.isfinite(f_res).any():
        lines.append(f"Resonance span: {np.nanmin(f_res) / 1e9:.6g} GHz to {np.nanmax(f_res) / 1e9:.6g} GHz")
        lines.append(f"Resonance standard deviation: {np.nanstd(f_res) / 1e6:.6g} MHz")
    if np.isfinite(s11_min).any():
        lines.append(f"S11 min mean: {np.nanmean(s11_min):.4g} dB")
        lines.append(f"S11 min standard deviation: {np.nanstd(s11_min):.4g} dB")
    lines.append("")
    lines.append("Generated files:")
    lines.extend(f"- {name}" for name in made)
    (out / "analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create plots from a LibreVNA characterization run.")
    parser.add_argument("run_dir", type=Path, help="Run directory containing summary.csv")
    parser.add_argument("--out", type=Path, default=None, help="Analysis output directory")
    parser.add_argument("--include-extra", action="store_true", help="Also write lower-level trace summary plots such as mean level, trace std dev, and phase slope")
    parser.add_argument("--include-histograms", action="store_true", help="Also write distribution histograms for resonance and S11 minimum")
    return parser


def run(args: argparse.Namespace) -> int:
    run_dir = args.run_dir
    summary_path = run_dir / "summary.csv"
    if not summary_path.exists():
        raise SystemExit(f"missing {summary_path}")
    out = args.out or (run_dir / "analysis")
    out.mkdir(parents=True, exist_ok=True)
    rows = load_summary(summary_path)
    if not rows:
        raise SystemExit("summary.csv has no rows")

    x = elapsed_hours(rows)
    made: List[str] = []
    plots = [
        ("f_res_Hz", "Resonance Frequency vs Time", "Frequency (GHz)", "resonance_frequency_vs_time.png", 1e-9),
        ("f_res_shift_Hz", "Resonance Shift vs Time", "Shift from first sweep (MHz)", "resonance_shift_vs_time.png", 1e-6),
        ("S11_min_dB", "S11 Minimum vs Time", "S11 minimum (dB)", "s11_min_vs_time.png"),
        ("BW_m10db_Hz", "-10 dB Bandwidth vs Time", "Bandwidth (MHz)", "bandwidth_vs_time.png", 1e-6),
        ("temp_1_C", "LibreVNA Temperature 1 vs Time", "Temperature (C)", "temperature_1_vs_time.png"),
        ("temp_2_C", "LibreVNA Temperature 2 vs Time", "Temperature (C)", "temperature_2_vs_time.png"),
        ("temp_3_C", "LibreVNA Temperature 3 vs Time", "Temperature (C)", "temperature_3_vs_time.png"),
    ]
    if args.include_extra:
        plots.extend([
            ("s11_mean_db", "S11 Mean Level vs Time", "Mean S11 (dB)", "s11_mean_vs_time.png"),
            ("s11_std_db", "S11 Trace Standard Deviation vs Time", "Std dev across trace (dB)", "s11_std_vs_time.png"),
            ("s11_phase_slope_deg_per_hz", "S11 Phase Slope vs Time", "deg/Hz", "s11_phase_slope_vs_time.png"),
            ("s21_mean_db", "S21 Mean Insertion vs Time", "Mean S21 (dB)", "s21_mean_vs_time.png"),
        ])
    for plot in plots:
        col_name, title, ylabel, filename = plot[:4]
        y_scale = plot[4] if len(plot) > 4 else 1.0
        if save_line_plot(out, x, column(rows, col_name), title, ylabel, filename, y_scale=y_scale):
            made.append(filename)
    if save_trace_overlay(run_dir, out, rows):
        made.append("trace_overlay_s11.png")
    if args.include_histograms:
        if save_histogram(out, column(rows, "f_res_Hz") / 1e9, "Resonance Frequency Distribution", "Frequency (GHz)", "f_res_histogram.png"):
            made.append("f_res_histogram.png")
        if save_histogram(out, column(rows, "S11_min_dB"), "S11 Minimum Distribution", "S11 minimum (dB)", "s11_min_histogram.png"):
            made.append("s11_min_histogram.png")
    write_report(out, rows, made)
    print(f"Wrote analysis to {out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
