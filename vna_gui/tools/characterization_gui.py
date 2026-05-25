r"""Run the standalone LibreVNA characterization tool window.

From ``vna_gui``:

    python tools\characterization_gui.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vna_tester.tools.characterization_gui import main


if __name__ == "__main__":
    raise SystemExit(main())
