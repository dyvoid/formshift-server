"""potrace tracing module: raster/png in, vector/svg out.

potrace is GPL-2.0 and is invoked strictly as a subprocess (aggregation, not
linking) — a licensing boundary, not a performance choice. Do not replace
this with a linked binding (pypotrace or similar); see the repo README and
architecture overview Constraints.

potrace's core is monochrome: it reads a graymap and thresholds it with the
blacklevel parameter (-k), exposed here as a live dial. PNG input is
converted to PGM in-process with Pillow before handing off.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from ..modules import ModuleError, ModuleManifest, ModuleResult, PortSpec
from .raster import _flatten

_TIMEOUT_SECONDS = 300


def find_potrace() -> str | None:
    """Locate the potrace binary: env var, PATH, then the dev tools/ convention."""
    env = os.environ.get("FORMSHIFT_POTRACE")
    if env and Path(env).is_file():
        return env
    on_path = shutil.which("potrace")
    if on_path:
        return on_path
    dev = Path("tools") / "potrace-1.16.win64" / "potrace.exe"
    if dev.is_file():
        return str(dev)
    return None


def _png_to_pgm(png_bytes: bytes) -> bytes:
    try:
        image: Image.Image = Image.open(io.BytesIO(png_bytes))
        # Composite transparency onto white before grayscaling: an alpha
        # channel dropped by a plain convert("L") would turn transparent
        # background into black and trace as solid ink.
        gray = _flatten(image).convert("L")
    except Exception as exc:
        raise ModuleError(f"could not decode PNG input: {exc}") from exc
    buffer = io.BytesIO()
    gray.save(buffer, format="PPM")  # Pillow writes PGM for mode "L" under the PPM writer
    return buffer.getvalue()


class PotraceModule:
    manifest = ModuleManifest(
        name="potrace.trace",
        version="1.16",  # tracks the potrace release; part of the cache key
        description="Trace a raster image to SVG with potrace (subprocess, GPL boundary)",
        inputs=(PortSpec("image", "raster/png"),),
        outputs=(PortSpec("svg", "vector/svg"),),
    )

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        binary = find_potrace()
        if binary is None:
            raise ModuleError(
                "potrace binary not found (set FORMSHIFT_POTRACE, add potrace to PATH, "
                "or place it at tools/potrace-1.16.win64/potrace.exe)"
            )

        try:
            blacklevel = float(params.get("blacklevel", 0.5))
            turdsize = int(params.get("turdsize", 2))
        except (TypeError, ValueError) as exc:
            raise ModuleError(f"invalid potrace params: {exc}") from exc
        if not 0.0 <= blacklevel <= 1.0:
            raise ModuleError(f"blacklevel must be in [0, 1], got {blacklevel}")
        if turdsize < 0:
            raise ModuleError(f"turdsize must be >= 0, got {turdsize}")

        pgm = _png_to_pgm(inputs["image"])
        command = [
            binary,
            "--svg",
            "--blacklevel",
            str(blacklevel),
            "--turdsize",
            str(turdsize),
            "--output",
            "-",
        ]
        try:
            result = subprocess.run(
                command, input=pgm, capture_output=True, timeout=_TIMEOUT_SECONDS, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise ModuleError(f"potrace timed out after {_TIMEOUT_SECONDS}s") from exc
        except OSError as exc:
            raise ModuleError(f"failed to run potrace: {exc}") from exc

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            raise ModuleError(f"potrace failed (exit {result.returncode}): {stderr}")

        return {"svg": ModuleResult(type="vector/svg", data=result.stdout)}
