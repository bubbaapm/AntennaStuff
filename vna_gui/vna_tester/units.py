"""
Free-form frequency parsing.

Accepts inputs like "2.4G", "915M", "2400 MHz", "1.575GHz", "100k",
"100000", "100 kHz", or just "2400" (interpreted as MHz by default).
Used by the marker entry box so the user can type whatever feels natural.
"""
from __future__ import annotations
import re
from typing import Optional


_FREQ_RE = re.compile(
    r"""^\s*
        ([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)   # numeric part
        \s*
        ([a-zA-Z]*)                         # optional unit suffix
        \s*$""",
    re.VERBOSE,
)

# Suffix → multiplier (Hz). Empty suffix means caller decides default.
_SUFFIXES = {
    "":     None,
    "hz":   1.0,
    "khz":  1e3,
    "k":    1e3,
    "mhz":  1e6,
    "m":    1e6,
    "ghz":  1e9,
    "g":    1e9,
    "thz":  1e12,
    "t":    1e12,
}


def parse_frequency(text: str, default_unit_hz: float = 1e6) -> Optional[float]:
    """
    Parse a frequency string.  Returns Hz, or None if the text is unparseable.

    `default_unit_hz` is the multiplier used when the user doesn't include a
    unit suffix.  1e6 (MHz) is a reasonable default for marker entry; pass
    1.0 if you want bare numbers to mean Hz.
    """
    if text is None:
        return None
    m = _FREQ_RE.match(text)
    if not m:
        return None
    num_str, suffix = m.group(1), m.group(2).lower()
    try:
        value = float(num_str)
    except ValueError:
        return None
    mult = _SUFFIXES.get(suffix, "MISSING")
    if mult == "MISSING":
        return None
    if mult is None:
        mult = default_unit_hz
    return value * mult


def format_freq_input(hz: float) -> str:
    """Format a frequency for display in an editable input field."""
    if hz >= 1e9:
        return f"{hz/1e9:g} GHz"
    if hz >= 1e6:
        return f"{hz/1e6:g} MHz"
    if hz >= 1e3:
        return f"{hz/1e3:g} kHz"
    return f"{hz:g} Hz"
