"""The core extension: classical modules sharing the server's own environment.

Architecturally just an extension like any other (design doc, Extensions);
nothing in the engine special-cases it.
"""

from .potrace import PotraceModule

__all__ = ["PotraceModule"]
