"""VNA Tester — entry shim. Run: python vna_tester.py"""
from __future__ import annotations
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from vna_tester.app import main

if __name__ == "__main__":
    sys.exit(main())
