"""The core extension: classical modules sharing the server's own environment.

Architecturally just an extension like any other (design doc, Extensions);
nothing in the engine special-cases it.
"""

from .potrace import PotraceModule
from .raster import (
    CropModule,
    DownsampleModule,
    LevelsModule,
    RotateModule,
    ThresholdModule,
)

__all__ = [
    "CropModule",
    "DownsampleModule",
    "LevelsModule",
    "PotraceModule",
    "RotateModule",
    "ThresholdModule",
]
