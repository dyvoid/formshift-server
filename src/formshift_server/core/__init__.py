"""The core extension: classical modules sharing the server's own environment.

Architecturally just an extension like any other (design doc, Extensions);
nothing in the engine special-cases it.
"""

from .color import ColorMaskModule, PosterizeModule, SvgColorizeModule, SvgMergeModule
from .potrace import PotraceModule
from .raster import (
    CropModule,
    DownsampleModule,
    InvertModule,
    LevelsModule,
    RotateModule,
    ThresholdModule,
)

__all__ = [
    "ColorMaskModule",
    "CropModule",
    "DownsampleModule",
    "InvertModule",
    "LevelsModule",
    "PosterizeModule",
    "PotraceModule",
    "RotateModule",
    "SvgColorizeModule",
    "SvgMergeModule",
    "ThresholdModule",
]
