"""Radar GUI entry point. Run from the repo root with: python radar_gui/radar_gui.py"""
from __future__ import annotations

import os
import sys


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from radar_gui.app import main


if __name__ == "__main__":
    sys.exit(main())
