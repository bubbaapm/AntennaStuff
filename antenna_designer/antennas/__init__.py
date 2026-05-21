"""Antenna registry — import every module so their decorators fire."""
from . import base            # noqa: F401
from . import patch           # noqa: F401
from . import wire            # noqa: F401
from . import aperture        # noqa: F401
from . import helical_loop    # noqa: F401
from . import phased          # noqa: F401
from . import printed_arrays  # noqa: F401
from . import spiral          # noqa: F401

from .base import (
    AntennaBase, Context, Input, Curve,
    available_antennas, get_antenna, register_antenna,
    C_LIGHT, ETA0,
)

__all__ = [
    "AntennaBase", "Context", "Input", "Curve",
    "available_antennas", "get_antenna", "register_antenna",
    "C_LIGHT", "ETA0",
]
