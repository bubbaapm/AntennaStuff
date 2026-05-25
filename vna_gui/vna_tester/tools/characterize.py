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
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from ..controller import SweepConfig, _parse_trace_data
from ..metrics import antenna_metrics
from ..scpi import ScpiClient, ScpiError
from ..trace import Trace, VNA_PARAMS


TOUCHSTONE_2P_ORDER = ("S11", "S21", "S12", "S22")


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


def _format_float(value: float) -> str:
    if value is None or not math.isfinite(float(value)):
        return ""
    return f"{float(value):.12g}"


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Log repeated LibreVNA sweeps for drift, repeatability, and control tests."
    )
    parser.add_argument("--host", default="localhost", help="SCPI host. Default: localhost")
    parser.add_argument("--port", type=int, default=19542, help="SCPI port. Default: 19542")
    parser.add_argument("--dut", required=True, help="DUT name for metadata and CSV rows")
    parser.add_argument(
        "--kind",
        default="antenna",
        choices=("antenna", "load", "open", "short", "thru", "cable", "other"),
        help="DUT/test kind. Default: antenna",
    )
    parser.add_argument("--notes", default="", help="Operator notes saved to metadata.json")
    parser.add_argument("--calibration", default="", help="Calibration file/path noted in metadata")
    parser.add_argument("--out", type=Path, required=True, help="Output run directory")
    parser.add_argument("--start", dest="start_hz", type=float, required=True, help="Sweep start in Hz")
    parser.add_argument("--stop", dest="stop_hz", type=float, required=True, help="Sweep stop in Hz")
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
) -> None:
    metadata = {
        "created_utc": _utc_now().isoformat().replace("+00:00", "Z"),
        "dut_name": args.dut,
        "dut_kind": args.kind,
        "notes": args.notes,
        "calibration_file": args.calibration,
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
    if args.stop_hz <= args.start_hz:
        raise SystemExit("--stop must be greater than --start")
    if args.points < 2:
        raise SystemExit("--points must be at least 2")
    if args.averaging < 1:
        raise SystemExit("--averaging must be at least 1")
    if args.count <= 0 and args.duration <= 0:
        args.count = 1

    args.out.mkdir(parents=True, exist_ok=True)
    cfg = SweepConfig(
        start_hz=args.start_hz,
        stop_hz=args.stop_hz,
        points=args.points,
        ifbw_hz=args.ifbw_hz,
        averaging=args.averaging,
        power_dbm=args.power_dbm,
    )
    csv_path = args.out / "summary.csv"
    device_id = ""
    started_at = time.monotonic()
    baseline_f_res: float | None = None

    client = ScpiClient(args.host, args.port, timeout=10.0)
    try:
        client.connect()
        try:
            device_id = client.query("*IDN?").strip()
        except ScpiError:
            device_id = ""
        configure_device(client, cfg, args.traces)
        initial_status = read_device_status(client)
        write_metadata(args.out / "metadata.json", args, cfg, device_id, initial_status)

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

    print(f"Wrote {csv_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
