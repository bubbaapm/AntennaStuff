#!/usr/bin/env python3
"""Prompted command-line launcher for LibreVNA characterization runs."""
from __future__ import annotations

import sys
from pathlib import Path


VNA_GUI_DIR = Path(__file__).resolve().parents[1]
if str(VNA_GUI_DIR) not in sys.path:
    sys.path.insert(0, str(VNA_GUI_DIR))

from vna_tester.tools.characterize import main


if __name__ == "__main__":
    raise SystemExit(main(["--interactive", *sys.argv[1:]]))
