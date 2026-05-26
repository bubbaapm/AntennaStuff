#!/usr/bin/env python3
"""Prompted analyzer launcher for existing LibreVNA characterization runs."""
from __future__ import annotations

import sys
from pathlib import Path


VNA_GUI_DIR = Path(__file__).resolve().parents[1]
if str(VNA_GUI_DIR) not in sys.path:
    sys.path.insert(0, str(VNA_GUI_DIR))

from vna_tester.tools.analyze_characterization import main


def _find_runs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    runs = [path.parent for path in root.rglob("summary.csv")]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


def _prompt(label: str, default: str = "") -> str:
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


def prompted_args() -> list[str]:
    runs_root = VNA_GUI_DIR / "characterization_runs"
    runs = _find_runs(runs_root)
    print("LibreVNA analysis setup")
    if runs:
        print("\nRecent runs:")
        for i, run in enumerate(runs[:20], start=1):
            try:
                shown = run.relative_to(VNA_GUI_DIR)
            except ValueError:
                shown = run
            print(f"  {i}. {shown}")
        default = "1"
    else:
        print("\nNo runs found under characterization_runs.")
        default = ""

    while True:
        choice = _prompt("Choose run number or path", default)
        if choice.isdigit() and runs and 1 <= int(choice) <= min(len(runs), 20):
            run_dir = runs[int(choice) - 1]
            break
        run_dir = Path(choice).expanduser()
        if not run_dir.is_absolute():
            run_dir = VNA_GUI_DIR / run_dir
        if (run_dir / "summary.csv").exists():
            break
        print("Choose a listed number or a folder containing summary.csv.")

    args = [str(run_dir)]
    include_extra = _prompt_bool("Include extra low-level plots", False)
    include_histograms = _prompt_bool("Include histogram/distribution plots", False)
    if include_extra:
        args.append("--include-extra")
    if include_histograms:
        args.append("--include-histograms")
    return args


if __name__ == "__main__":
    argv = sys.argv[1:] or prompted_args()
    raise SystemExit(main(argv))
