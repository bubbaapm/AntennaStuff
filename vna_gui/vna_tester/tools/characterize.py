"""Long-running LibreVNA characterization logger.

Run from ``vna_gui`` with for example:

    python -m vna_tester.tools.characterize --dut "Patch antenna" \
        --kind antenna --start 2.3e9 --stop 2.6e9 --points 1001 \
        --interval 300 --count 96 --out runs/patch_overnight
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from ..controller import SweepConfig, _parse_trace_data
from ..launcher import LibreVnaLauncher, is_port_open
from ..metrics import antenna_metrics
from ..scpi import ScpiClient, ScpiError
from ..trace import Trace, VNA_PARAMS


TOUCHSTONE_2P_ORDER = ("S11", "S21", "S12", "S22")
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp_slug(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _safe_name(value: str) -> str:
    chars = []
    for ch in value.strip():
        if ch.isalnum() or ch in ("-", "_"):
            chars.append(ch)
        elif ch.isspace() or ch in (".", ",", ":", "/"):
            chars.append("_")
    return "".join(chars).strip("_") or "dut"


def default_run_dir(dut_name: str, when: datetime | None = None) -> Path:
    when = when or _utc_now()
    return PACKAGE_ROOT / "characterization_runs" / f"{_safe_name(dut_name)}_{when.strftime('%Y%m%d_%H%M%S')}"


def _format_float(value: float) -> str:
    if value is None or not math.isfinite(float(value)):
        return ""
    return f"{float(value):.12g}"


def _find_files_limited(root: Path, name: str, max_depth: int = 4) -> List[Path]:
    if not root.exists():
        return []
    root = root.resolve()
    found: List[Path] = []
    stack = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            for child in cur.iterdir():
                if child.is_file() and child.name == name:
                    found.append(child)
                elif child.is_dir() and depth < max_depth and not child.name.startswith("."):
                    stack.append((child, depth + 1))
        except OSError:
            continue
    return found


def calibration_search_roots() -> List[Path]:
    return [
        Path.cwd() / "cals",
        Path.cwd() / "Cals",
        PACKAGE_ROOT / "cals",
        PACKAGE_ROOT / "Cals",
        Path.home() / "librevna",
        Path.home() / "LibreVNA",
    ]


def list_calibrations() -> List[Path]:
    files: List[Path] = []
    seen: set[Path] = set()
    for root in calibration_search_roots():
        if not root.exists():
            continue
        try:
            for path in root.rglob("*.cal"):
                resolved = path.resolve()
                if resolved not in seen:
                    files.append(path)
                    seen.add(resolved)
        except OSError:
            pass
    return sorted(files, key=calibration_sort_key, reverse=True)


def _git_file_timestamp(path: Path) -> float | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(PACKAGE_ROOT), "log", "-1", "--format=%ct", "--", str(path.resolve())],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = proc.stdout.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def calibration_sort_key(path: Path) -> Tuple[float, float, str]:
    git_ts = _git_file_timestamp(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (git_ts or 0.0, mtime, path.name.lower())


def auto_find_librevna_gui(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit
    env_value = os.environ.get("LIBREVNA_GUI") or os.environ.get("LIBREVNA_GUI_PATH")
    if env_value:
        candidate = Path(env_value).expanduser()
        if candidate.exists():
            return candidate

    candidates = [
        Path.cwd() / "LibreVNA-GUI",
        Path.cwd() / "LibreVNA-GUI.exe",
        PACKAGE_ROOT / "tools" / "librevna" / "LibreVNA-GUI",
        PACKAGE_ROOT / ".." / "LibreVNA" / "release" / "LibreVNA-GUI.exe",
        Path.home() / "librevna" / "LibreVNA-GUI",
        Path.home() / "LibreVNA-GUI",
    ]
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if candidate.exists():
            return candidate

    search_roots = [
        PACKAGE_ROOT / "tools" / "librevna",
        Path.home() / "librevna",
        Path.home() / "LibreVNA",
        Path.home() / "Downloads",
    ]
    found: List[Path] = []
    for root in search_roots:
        found.extend(_find_files_limited(root.expanduser(), "LibreVNA-GUI", max_depth=4))
    return sorted(found, key=lambda p: len(str(p)))[0] if found else None


def find_calibration(value: str) -> Path | None:
    if not value:
        return None
    if value.lower() in ("latest", "auto"):
        files = list_calibrations()
        return files[0] if files else None
    return Path(value).expanduser()


def load_calibration(client: ScpiClient, path: Path) -> None:
    ok = client.query_bool(f':VNA:CAL:LOAD? "{path}"')
    if not ok:
        raise RuntimeError(f"LibreVNA-GUI rejected calibration file: {path}")
    time.sleep(0.35)


def read_device_sweep_config(client: ScpiClient) -> SweepConfig:
    return SweepConfig(
        start_hz=client.query_float(":VNA:FREQ:START?"),
        stop_hz=client.query_float(":VNA:FREQ:STOP?"),
        points=client.query_int(":VNA:ACQ:POINTS?"),
        ifbw_hz=client.query_float(":VNA:ACQ:IFBW?"),
        averaging=client.query_int(":VNA:ACQ:AVG?"),
        power_dbm=client.query_float(":VNA:STIM:LVL?"),
    )


def configure_device(client: ScpiClient, cfg: SweepConfig, traces: Sequence[str]) -> None:
    client.write(":DEV:CONN")
    client.write(":DEV:MODE VNA")
    client.write(":VNA:ACQ:STOP")
    client.write(":VNA:SWEEP FREQUENCY")
    client.write(f":VNA:FREQ:START {cfg.start_hz:.6f}")
    client.write(f":VNA:FREQ:STOP {cfg.stop_hz:.6f}")
    client.write(f":VNA:ACQ:POINTS {int(cfg.points)}")
    client.write(f":VNA:ACQ:IFBW {cfg.ifbw_hz:.3f}")
    client.write(f":VNA:ACQ:AVG {max(1, int(cfg.averaging))}")
    client.write(f":VNA:STIM:LVL {cfg.power_dbm:.2f}")
    client.write(":VNA:ACQ:SINGLE TRUE")

    existing = set(_split_list(client.query(":VNA:TRAC:LIST?")))
    for trace in traces:
        if trace not in existing:
            client.write(f":VNA:TRAC:NEW {trace}")
        client.write(f":VNA:TRAC:PAR {trace} {trace}")


def _split_list(reply: str) -> List[str]:
    return [part.strip() for part in reply.split(",") if part.strip()]


def wait_for_sweep(client: ScpiClient, averaging: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    saw_incomplete = False
    time.sleep(0.15)
    while time.monotonic() < deadline:
        try:
            finished = client.query_bool(":VNA:ACQ:FIN?")
            level = client.query_int(":VNA:ACQ:AVGLEV?")
        except ScpiError:
            time.sleep(0.2)
            continue
        if not finished or level < max(1, averaging):
            saw_incomplete = True
        if finished and level >= max(1, averaging) and saw_incomplete:
            return
        if finished and level >= max(1, averaging) and time.monotonic() + 0.25 < deadline:
            time.sleep(0.25)
            return
        time.sleep(0.2)
    raise TimeoutError(f"sweep did not finish within {timeout_s:.1f} s")


def acquire_traces(
    client: ScpiClient,
    traces: Sequence[str],
    averaging: int,
    timeout_s: float,
) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    client.write(":VNA:ACQ:SINGLE TRUE")
    client.write(":VNA:ACQ:RUN TRUE")
    wait_for_sweep(client, averaging=averaging, timeout_s=timeout_s)
    out: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for trace in traces:
        payload = client.query(f":VNA:TRAC:DATA? {trace}")
        freq, values = _parse_trace_data(payload)
        if freq.size == 0:
            raise RuntimeError(f"{trace} returned no data")
        out[trace] = (freq, values)
    return out


def _touchstone_text(traces: Dict[str, Tuple[np.ndarray, np.ndarray]]) -> str:
    names = list(traces)
    if len(names) == 1:
        ordered = names
    elif all(name in traces for name in TOUCHSTONE_2P_ORDER):
        ordered = list(TOUCHSTONE_2P_ORDER)
    else:
        raise ValueError("Touchstone writer supports one trace or a full S11/S21/S12/S22 set")

    freq_ref = traces[ordered[0]][0]
    for name in ordered[1:]:
        if traces[name][0].shape != freq_ref.shape or not np.allclose(traces[name][0], freq_ref):
            raise ValueError(f"{name} frequency grid differs from {ordered[0]}")

    lines = ["# Hz S RI R 50"]
    for i, freq in enumerate(freq_ref):
        row = [f"{freq:.0f}"]
        for name in ordered:
            value = traces[name][1][i]
            row.append(f"{value.real:.12g} {value.imag:.12g}")
        lines.append(" ".join(row))
    lines.append("")
    return "\n".join(lines)


def write_raw_touchstone(
    out_dir: Path,
    stem: str,
    traces: Dict[str, Tuple[np.ndarray, np.ndarray]],
) -> List[Path]:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    if len(traces) == 1 or all(name in traces for name in TOUCHSTONE_2P_ORDER):
        suffix = ".s2p" if all(name in traces for name in TOUCHSTONE_2P_ORDER) else ".s1p"
        path = raw_dir / f"{stem}{suffix}"
        path.write_text(_touchstone_text(traces), encoding="utf-8")
        return [path]

    written: List[Path] = []
    for name, data in traces.items():
        path = raw_dir / f"{stem}_{name.lower()}.s1p"
        path.write_text(_touchstone_text({name: data}), encoding="utf-8")
        written.append(path)
    return written


def summarize_trace(name: str, freq: np.ndarray, values: np.ndarray) -> Dict[str, float]:
    mag_db = 20.0 * np.log10(np.maximum(np.abs(values), 1e-12))
    phase = np.unwrap(np.angle(values))
    phase_deg = np.rad2deg(phase)
    if freq.size >= 2:
        slope = float(np.polyfit(freq, phase_deg, 1)[0])
    else:
        slope = 0.0
    prefix = name.lower()
    return {
        f"{prefix}_mean_db": float(np.mean(mag_db)),
        f"{prefix}_std_db": float(np.std(mag_db)),
        f"{prefix}_min_db": float(np.min(mag_db)),
        f"{prefix}_max_db": float(np.max(mag_db)),
        f"{prefix}_ripple_db": float(np.max(mag_db) - np.min(mag_db)),
        f"{prefix}_phase_mean_deg": float(np.mean(phase_deg)),
        f"{prefix}_phase_std_deg": float(np.std(phase_deg)),
        f"{prefix}_phase_slope_deg_per_hz": slope,
    }


def summarize_s11(freq: np.ndarray, values: np.ndarray, target_db: float) -> Dict[str, float]:
    trace = Trace(name="S11", parameter="S11", freq=freq, s=values)
    metrics = antenna_metrics(trace, target_db=target_db)
    return {
        "f_res_Hz": metrics.f_resonance_hz,
        "S11_min_dB": metrics.s11_min_db,
        "VSWR": metrics.vswr_at_resonance,
        "f_low_m10db_Hz": metrics.f_low_m10db_hz or float("nan"),
        "f_high_m10db_Hz": metrics.f_high_m10db_hz or float("nan"),
        "BW_m10db_Hz": metrics.bandwidth_m10db_hz,
        "Fractional_BW_pct": metrics.fractional_bw_pct,
        "Re_Z_ohm": metrics.impedance_at_resonance.real,
        "Im_Z_ohm": metrics.impedance_at_resonance.imag,
        "Q": metrics.quality_factor,
        "Mismatch_loss_dB": metrics.mismatch_loss_db,
    }


CSV_FIELDS = [
    "index",
    "timestamp_utc",
    "elapsed_s",
    "dut_name",
    "dut_kind",
    "device_id",
    "pll_unlocked",
    "adc_overload",
    "source_unleveled",
    "reference_source",
    "device_temperatures",
    "temp_1_C",
    "temp_2_C",
    "temp_3_C",
    "calibration_file",
    "raw_files",
    "start_Hz",
    "stop_Hz",
    "points",
    "ifbw_Hz",
    "averaging",
    "power_dBm",
    "f_res_Hz",
    "f_res_shift_Hz",
    "S11_min_dB",
    "VSWR",
    "f_low_m10db_Hz",
    "f_high_m10db_Hz",
    "BW_m10db_Hz",
    "Fractional_BW_pct",
    "Re_Z_ohm",
    "Im_Z_ohm",
    "Q",
    "Mismatch_loss_dB",
    "s11_mean_db",
    "s11_std_db",
    "s11_min_db",
    "s11_max_db",
    "s11_ripple_db",
    "s11_phase_mean_deg",
    "s11_phase_std_deg",
    "s11_phase_slope_deg_per_hz",
    "s21_mean_db",
    "s21_std_db",
    "s21_min_db",
    "s21_max_db",
    "s21_ripple_db",
    "s21_phase_mean_deg",
    "s21_phase_std_deg",
    "s21_phase_slope_deg_per_hz",
]


def read_device_status(client: ScpiClient) -> Dict[str, str]:
    commands = {
        "pll_unlocked": ":DEVICE:STATUS:UNLOCKED?",
        "adc_overload": ":DEVICE:STATUS:ADCOVERLOAD?",
        "source_unleveled": ":DEVICE:STATUS:UNLEVEL?",
        "reference_source": ":DEVICE:REFERENCE:IN?",
        "device_temperatures": ":DEVICE:INFO:TEMPERATURES?",
    }
    status = {}
    for key, cmd in commands.items():
        try:
            status[key] = client.query(cmd).strip()
        except ScpiError:
            status[key] = ""
    return status


def parse_temperatures(raw: str) -> List[float]:
    values: List[float] = []
    for part in raw.replace(",", "/").split("/"):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(float(part))
        except ValueError:
            continue
    return values


def build_row(
    index: int,
    started_at: float,
    timestamp: datetime,
    args: argparse.Namespace,
    cfg: SweepConfig,
    device_id: str,
    device_status: Dict[str, str],
    raw_paths: Sequence[Path],
    traces: Dict[str, Tuple[np.ndarray, np.ndarray]],
    baseline_f_res: float | None,
) -> Tuple[Dict[str, str], float | None]:
    row: Dict[str, object] = {
        "index": index,
        "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "elapsed_s": time.monotonic() - started_at,
        "dut_name": args.dut,
        "dut_kind": args.kind,
        "device_id": device_id,
        "pll_unlocked": device_status.get("pll_unlocked", ""),
        "adc_overload": device_status.get("adc_overload", ""),
        "source_unleveled": device_status.get("source_unleveled", ""),
        "reference_source": device_status.get("reference_source", ""),
        "device_temperatures": device_status.get("device_temperatures", ""),
        "calibration_file": args.calibration or "",
        "raw_files": ";".join(str(path.relative_to(args.out)) for path in raw_paths),
        "start_Hz": cfg.start_hz,
        "stop_Hz": cfg.stop_hz,
        "points": cfg.points,
        "ifbw_Hz": cfg.ifbw_hz,
        "averaging": cfg.averaging,
        "power_dBm": cfg.power_dbm,
    }
    temps = parse_temperatures(device_status.get("device_temperatures", ""))
    for i in range(3):
        row[f"temp_{i + 1}_C"] = temps[i] if i < len(temps) else float("nan")
    for name, (freq, values) in traces.items():
        row.update(summarize_trace(name, freq, values))
    if "S11" in traces:
        row.update(summarize_s11(*traces["S11"], target_db=args.target_db))
        current_f_res = float(row["f_res_Hz"])
        if baseline_f_res is None:
            baseline_f_res = current_f_res
        row["f_res_shift_Hz"] = current_f_res - baseline_f_res
    else:
        row["f_res_shift_Hz"] = float("nan")

    return {field: _format_float(row[field]) if isinstance(row.get(field), float) else str(row.get(field, ""))
            for field in CSV_FIELDS}, baseline_f_res


def parse_traces(value: str) -> List[str]:
    traces = [part.strip().upper() for part in value.split(",") if part.strip()]
    bad = [trace for trace in traces if trace not in VNA_PARAMS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown trace(s): {', '.join(bad)}")
    if not traces:
        raise argparse.ArgumentTypeError("at least one trace is required")
    return traces


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _prompt_text(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_bool(label: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        value = input(f"{label} [{hint}]: ").strip().lower()
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("Please enter y or n.")


def _prompt_choice(label: str, choices: Sequence[str], default: str) -> str:
    joined = "/".join(choices)
    while True:
        value = _prompt_text(f"{label} ({joined})", default).lower()
        if value in choices:
            return value
        print(f"Please choose one of: {', '.join(choices)}")


def _prompt_float(label: str, default: float) -> float:
    while True:
        value = _prompt_text(label, f"{default:g}")
        try:
            return float(value)
        except ValueError:
            print("Please enter a number.")


def _prompt_int(label: str, default: int, minimum: int = 0) -> int:
    while True:
        value = _prompt_text(label, str(default))
        try:
            parsed = int(value)
        except ValueError:
            print("Please enter a whole number.")
            continue
        if parsed >= minimum:
            return parsed
        print(f"Please enter at least {minimum}.")


def apply_interactive_prompts(args: argparse.Namespace) -> argparse.Namespace:
    print("LibreVNA characterization setup")
    print("Press Enter to accept defaults.\n")

    args.dut = _prompt_text("Test/DUT name", args.dut or "50 ohm load dry run")
    args.kind = _prompt_choice(
        "Kind",
        ("antenna", "load", "open", "short", "thru", "cable", "other"),
        args.kind or "antenna",
    )
    args.notes = _prompt_text("Notes", args.notes or "")

    cals = list_calibrations()
    if cals:
        print("\nCalibration files:")
        for i, path in enumerate(cals, start=1):
            try:
                shown = path.relative_to(PACKAGE_ROOT)
            except ValueError:
                shown = path
            print(f"  {i}. {shown}")
        print("  0. No calibration")
        default_cal = "1"
        while True:
            choice = _prompt_text("Choose calibration number, path, latest, or 0", default_cal)
            if choice == "0":
                args.calibration = ""
                break
            if choice.lower() in ("latest", "auto"):
                args.calibration = choice.lower()
                break
            if choice.isdigit() and 1 <= int(choice) <= len(cals):
                args.calibration = str(cals[int(choice) - 1])
                break
            candidate = Path(choice).expanduser()
            if candidate.exists():
                args.calibration = str(candidate)
                break
            print("Choose a listed number, 'latest', 0, or an existing .cal path.")
    else:
        args.calibration = _prompt_text("Calibration path, latest, or blank", args.calibration or "")

    args.use_cal_sweep = _prompt_bool("Use sweep grid from loaded calibration/active VNA", args.use_cal_sweep)
    if not args.use_cal_sweep:
        args.start_hz = _prompt_float("Start Hz", args.start_hz or 2.3e9)
        args.stop_hz = _prompt_float("Stop Hz", args.stop_hz or 2.6e9)
        args.points = _prompt_int("Points", args.points or 1001, minimum=2)
    else:
        print("Sweep start/stop/points will be read from LibreVNA after calibration loads.")

    args.ifbw_hz = _prompt_float("IFBW Hz", args.ifbw_hz or 1000.0)
    args.averaging = _prompt_int("Averaging", args.averaging or 4, minimum=1)
    args.power_dbm = _prompt_float("Power dBm", args.power_dbm if args.power_dbm is not None else -10.0)

    default_traces = "S11,S21,S12,S22" if args.kind in ("thru", "cable") else "S11"
    while True:
        try:
            args.traces = parse_traces(_prompt_text("Traces", default_traces))
            break
        except argparse.ArgumentTypeError as exc:
            print(exc)

    args.interval = _prompt_float("Interval between sweep starts, seconds", args.interval or 300.0)
    args.count = _prompt_int("Sweep count (0 to use duration)", args.count or 0, minimum=0)
    if args.count <= 0:
        args.duration = _prompt_float("Duration seconds", args.duration or 3600.0)
    else:
        args.duration = 0.0
    args.timeout = _prompt_float("Per-sweep timeout seconds", args.timeout or 120.0)
    args.target_db = _prompt_float("Return-loss bandwidth target dB", args.target_db or -10.0)

    default_out = default_run_dir(args.dut)
    args.out = Path(_prompt_text("Output run folder", str(args.out or default_out)))
    args.show_librevna_gui = _prompt_bool("Show LibreVNA-GUI window", args.show_librevna_gui)
    args.keep_librevna_gui = _prompt_bool("Keep LibreVNA-GUI running after test", args.keep_librevna_gui)
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Log repeated LibreVNA sweeps for drift, repeatability, and control tests."
    )
    parser.add_argument("--host", default="localhost", help="SCPI host. Default: localhost")
    parser.add_argument("--port", type=int, default=19542, help="SCPI port. Default: 19542")
    parser.add_argument("--librevna-gui", type=Path, default=None, help="Optional path to LibreVNA-GUI. If omitted, common Pi/Linux/Windows locations are searched")
    parser.add_argument("--show-librevna-gui", action="store_true", help="Start LibreVNA-GUI with its visible window instead of --no-gui")
    parser.add_argument("--keep-librevna-gui", action="store_true", help="Leave LibreVNA-GUI running after the characterization run if this script started it")
    parser.add_argument("--interactive", action="store_true", help="Prompt for run settings instead of requiring all options up front")
    parser.add_argument("--dut", default="", help="DUT name for metadata and CSV rows")
    parser.add_argument(
        "--kind",
        default="antenna",
        choices=("antenna", "load", "open", "short", "thru", "cable", "other"),
        help="DUT/test kind. Default: antenna",
    )
    parser.add_argument("--notes", default="", help="Operator notes saved to metadata.json")
    parser.add_argument("--calibration", default="", help="Calibration .cal to load before the run, or 'latest' to load the newest .cal found in common cals folders")
    parser.add_argument("--use-cal-sweep", action="store_true", help="After loading calibration, use the sweep settings stored in the calibration/active VNA instead of CLI sweep values")
    parser.add_argument("--out", type=Path, default=None, help="Output run directory")
    parser.add_argument("--start", dest="start_hz", type=float, default=None, help="Sweep start in Hz. Optional when --use-cal-sweep is set")
    parser.add_argument("--stop", dest="stop_hz", type=float, default=None, help="Sweep stop in Hz. Optional when --use-cal-sweep is set")
    parser.add_argument("--points", type=int, default=1001, help="Sweep points. Default: 1001")
    parser.add_argument("--ifbw", dest="ifbw_hz", type=positive_float, default=1000.0, help="IFBW in Hz")
    parser.add_argument("--averaging", type=int, default=4, help="Averaging count. Default: 4")
    parser.add_argument("--power", dest="power_dbm", type=float, default=-10.0, help="Source power in dBm")
    parser.add_argument("--traces", type=parse_traces, default=["S11"], help="Comma list, e.g. S11 or S11,S21,S12,S22")
    parser.add_argument("--interval", type=nonnegative_float, default=300.0, help="Seconds between sweep starts")
    parser.add_argument("--count", type=int, default=0, help="Number of sweeps. 0 means use --duration")
    parser.add_argument("--duration", type=nonnegative_float, default=0.0, help="Total run duration in seconds")
    parser.add_argument("--timeout", type=positive_float, default=120.0, help="Per-sweep timeout in seconds")
    parser.add_argument("--target-db", type=float, default=-10.0, help="Return-loss bandwidth threshold")
    return parser


def write_metadata(
    path: Path,
    args: argparse.Namespace,
    cfg: SweepConfig,
    device_id: str,
    device_status: Dict[str, str],
    calibration_file: str,
) -> None:
    metadata = {
        "created_utc": _utc_now().isoformat().replace("+00:00", "Z"),
        "dut_name": args.dut,
        "dut_kind": args.kind,
        "notes": args.notes,
        "calibration_file": calibration_file,
        "device_id": device_id,
        "device_status_at_start": device_status,
        "scpi": {"host": args.host, "port": args.port},
        "sweep": asdict(cfg),
        "traces": args.traces,
        "interval_s": args.interval,
        "count": args.count,
        "duration_s": args.duration,
        "target_db": args.target_db,
    }
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def planned_indices(args: argparse.Namespace) -> Iterable[int]:
    if args.count > 0:
        return range(1, args.count + 1)
    if args.duration <= 0:
        return range(1, 2)
    count = max(1, int(math.floor(args.duration / max(args.interval, 1e-9))) + 1)
    return range(1, count + 1)


def run(args: argparse.Namespace) -> int:
    if not args.dut:
        raise SystemExit("--dut is required unless --interactive is set")
    if args.out is None:
        args.out = default_run_dir(args.dut)
    if (args.start_hz is None or args.stop_hz is None) and not args.use_cal_sweep:
        raise SystemExit("--start and --stop are required unless --use-cal-sweep is set")
    if args.start_hz is not None and args.stop_hz is not None and args.stop_hz <= args.start_hz:
        raise SystemExit("--stop must be greater than --start")
    if args.points < 2:
        raise SystemExit("--points must be at least 2")
    if args.averaging < 1:
        raise SystemExit("--averaging must be at least 1")
    if args.count <= 0 and args.duration <= 0:
        args.count = 1

    args.out.mkdir(parents=True, exist_ok=True)
    cfg = SweepConfig()
    csv_path = args.out / "summary.csv"
    device_id = ""
    started_at = time.monotonic()
    baseline_f_res: float | None = None
    launcher: LibreVnaLauncher | None = None

    if not is_port_open(args.host, args.port):
        gui_path = auto_find_librevna_gui(args.librevna_gui)
        if gui_path is None:
            raise SystemExit(
                "SCPI server is not reachable and LibreVNA-GUI was not found. "
                "Unzip LibreVNA-GUI under ~/librevna, set LIBREVNA_GUI, or pass "
                "--librevna-gui /path/to/LibreVNA-GUI."
            )
        print(f"Starting LibreVNA-GUI: {gui_path}")
        launcher = LibreVnaLauncher(gui_path, host=args.host, port=args.port)
        ok = launcher.ensure_running(wait_seconds=15.0, headless=not args.show_librevna_gui)
        if not ok:
            launcher.stop()
            raise SystemExit(f"could not start or reach LibreVNA-GUI at {gui_path}")

    client = ScpiClient(args.host, args.port, timeout=10.0)
    try:
        client.connect()
        try:
            device_id = client.query("*IDN?").strip()
        except ScpiError:
            device_id = ""
        calibration_file = ""
        cal_path = find_calibration(args.calibration)
        if args.calibration and cal_path is None:
            raise SystemExit(f"no calibration file found for {args.calibration!r}")
        if cal_path is not None:
            if not cal_path.exists():
                raise SystemExit(f"calibration file does not exist: {cal_path}")
            print(f"Loading calibration: {cal_path}")
            load_calibration(client, cal_path)
            calibration_file = str(cal_path)
            args.calibration = calibration_file
        if args.use_cal_sweep:
            cfg = read_device_sweep_config(client)
            cfg.ifbw_hz = args.ifbw_hz
            cfg.averaging = args.averaging
            cfg.power_dbm = args.power_dbm
        else:
            assert args.start_hz is not None and args.stop_hz is not None
            cfg = SweepConfig(
                start_hz=args.start_hz,
                stop_hz=args.stop_hz,
                points=args.points,
                ifbw_hz=args.ifbw_hz,
                averaging=args.averaging,
                power_dbm=args.power_dbm,
            )
        configure_device(client, cfg, args.traces)
        initial_status = read_device_status(client)
        write_metadata(args.out / "metadata.json", args, cfg, device_id, initial_status, calibration_file)

        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()

            next_start = time.monotonic()
            total = list(planned_indices(args))
            for index in total:
                now = time.monotonic()
                if now < next_start:
                    time.sleep(next_start - now)
                timestamp = _utc_now()
                traces = acquire_traces(client, args.traces, args.averaging, args.timeout)
                device_status = read_device_status(client)
                stem = f"{index:04d}_{_timestamp_slug(timestamp)}_{_safe_name(args.dut)}"
                raw_paths = write_raw_touchstone(args.out, stem, traces)
                row, baseline_f_res = build_row(
                    index=index,
                    started_at=started_at,
                    timestamp=timestamp,
                    args=args,
                    cfg=cfg,
                    device_id=device_id,
                    device_status=device_status,
                    raw_paths=raw_paths,
                    traces=traces,
                    baseline_f_res=baseline_f_res,
                )
                writer.writerow(row)
                fh.flush()
                print(
                    f"[{index}/{len(total)}] {row['timestamp_utc']} "
                    f"S11_min={row.get('S11_min_dB', '')} dB "
                    f"f_res={row.get('f_res_Hz', '')} Hz"
                )
                next_start += args.interval
    finally:
        try:
            client.write(":VNA:ACQ:RUN FALSE")
        except Exception:
            pass
        client.close()
        if launcher is not None and not args.keep_librevna_gui:
            launcher.stop()

    print(f"Wrote {csv_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interactive:
        args = apply_interactive_prompts(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
