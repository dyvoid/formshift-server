"""Color separation modules: posterize, per-color masks, SVG colorize/merge.

The multi-color pattern (design doc, Pipeline architecture): posterize to N
flat colors, one binary mask per color, one trace per mask, recolor each
trace, merge as a binary tree (ADR 0009).

SVG handling notes: svg.colorize and svg.merge operate on potrace-generated
SVG (a single <g> wrapping the paths). They parse with ElementTree, not
regex, but make no attempt to handle arbitrary SVG features (defs, CSS,
nested transforms beyond the group's own); that is documented scope, not an
accident.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
from PIL import Image, ImageFilter
from skimage.color import rgb2lab

from ..modules import ModuleError, ModuleManifest, ModuleResult, PortSpec
from .raster import RASTER_PNG, _decode, _encode, _flatten, _int_param

VECTOR_SVG = "vector/svg"

_SVG_NS = "http://www.w3.org/2000/svg"


def _validate_palette(raw: Any) -> list[tuple[int, int, int]]:
    """Validate an explicit palette (ADR 0020): 2-256 unique #rrggbb strings."""
    if not isinstance(raw, list):
        raise ModuleError(f"palette must be a list of #rrggbb strings, got {type(raw).__name__}")
    if not 2 <= len(raw) <= 256:
        raise ModuleError(f"palette length must be in [2, 256], got {len(raw)}")
    entries: list[tuple[int, int, int]] = []
    for position, entry in enumerate(raw):
        if not (
            isinstance(entry, str)
            and entry.startswith("#")
            and len(entry) == 7
            and all(character in "0123456789abcdefABCDEF" for character in entry[1:])
        ):
            raise ModuleError(f"palette[{position}] must be a #rrggbb hex color, got {entry!r}")
        rgb = (int(entry[1:3], 16), int(entry[3:5], 16), int(entry[5:7], 16))
        if rgb in entries:
            raise ModuleError(f"palette[{position}] duplicates an earlier entry: {entry!r}")
        entries.append(rgb)
    return entries


class PosterizeModule:
    """Quantize to N flat colors. Output is a palette-mode PNG; the palette
    (index -> RGB) is readable by any PNG decoder, which is how clients and
    the colormask module learn the color of each index.

    Two mutually exclusive modes (ADR 0020): `colors` (median-cut, the
    default) or an explicit `palette` — nearest entry by CIELAB distance,
    PLTE in the supplied order, ties to the lowest index."""

    manifest = ModuleManifest(
        name="image.posterize",
        version="1.0",
        description="Quantize to N flat colors (palette-mode PNG output)",
        inputs=(PortSpec("image", RASTER_PNG),),
        outputs=(PortSpec("image", RASTER_PNG),),
    )

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        if "palette" in params and "colors" in params:
            raise ModuleError("palette and colors are mutually exclusive; give one, not both")
        image = _flatten(_decode(inputs["image"])).convert("RGB")
        if "palette" in params:
            palette = _validate_palette(params["palette"])
            return {"image": _encode(_map_to_palette(image, palette))}
        colors = _int_param(params, "colors", 8)
        if not 2 <= colors <= 256:
            raise ModuleError(f"colors must be in [2, 256], got {colors}")
        quantized = image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        return {"image": _encode(quantized)}


def _map_to_palette(image: Image.Image, palette: list[tuple[int, int, int]]) -> Image.Image:
    """Map each pixel to the nearest palette entry in CIELAB (ADR 0020).

    np.argmin's first-occurrence rule is the deterministic lowest-index
    tie-break the contract requires.
    """
    pixels = np.asarray(image, dtype=np.float64) / 255.0
    pixels_lab = rgb2lab(pixels).reshape(-1, 1, 3)
    palette_lab = rgb2lab(np.asarray(palette, dtype=np.float64).reshape(1, -1, 3) / 255.0)
    distances = np.square(pixels_lab - palette_lab).sum(axis=2)
    indices = distances.argmin(axis=1).astype(np.uint8).reshape(image.height, image.width)
    output = Image.fromarray(indices, mode="P")
    output.putpalette([channel for entry in palette for channel in entry])
    return output


class ColorMaskModule:
    """Extract one palette index from a posterized image as a binary mask
    (index pixels black, everything else white — ready for tracing).

    Optional `grow` (ADR 0021) dilates the black region by N pixels so
    adjacent traces overlap at their shared boundary (trapping).

    An index in [0, 256) that no pixel uses yields an all-white (empty)
    mask rather than an error (ADR 0022)."""

    manifest = ModuleManifest(
        name="image.colormask",
        version="1.0",
        description="Binary mask of one palette index of a posterized image",
        inputs=(PortSpec("image", RASTER_PNG),),
        outputs=(PortSpec("mask", RASTER_PNG),),
    )

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        index = _int_param(params, "index", 0)
        image = _decode(inputs["image"])
        if image.mode != "P":
            raise ModuleError(
                "colormask needs a palette-mode image (the output of image.posterize)"
            )
        if not 0 <= index < 256:
            raise ModuleError(f"index must be in [0, 256), got {index}")
        # An in-range index no pixel maps to is an empty selection, not an
        # error: an explicit palette (ADR 0020) may carry unused entries, and
        # the LUT below yields an all-white "nothing selected" mask (ADR 0022).
        # point() with an explicit target mode maps raw palette indices through
        # the LUT, sidestepping palette color interpretation entirely.
        lut = [255] * 256
        lut[index] = 0
        mask = image.point(lut, mode="L")
        grow = params.get("grow", 0)
        if isinstance(grow, bool) or not isinstance(grow, int) or grow < 0:
            raise ModuleError(f"grow must be a non-negative integer, got {grow!r}")
        if grow > 0:
            # MinFilter spreads the black (selected) region: a square
            # structuring element of radius `grow`, deterministic per
            # module_version (ADR 0021).
            mask = mask.filter(ImageFilter.MinFilter(2 * grow + 1))
        return {"mask": ModuleResult(type=RASTER_PNG, data=_encode(mask).data)}


def _parse_svg(data: bytes, what: str) -> ET.Element:
    try:
        return ET.fromstring(data.decode("utf-8"))
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise ModuleError(f"could not parse {what} as SVG: {exc}") from exc


def _serialize_svg(root: ET.Element) -> bytes:
    ET.register_namespace("", _SVG_NS)
    data: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return data


class SvgColorizeModule:
    """Set the fill color on the SVG's top-level groups/paths."""

    manifest = ModuleManifest(
        name="svg.colorize",
        version="1.0",
        description="Set fill color (hex) on an SVG's top-level groups and paths",
        inputs=(PortSpec("svg", VECTOR_SVG),),
        outputs=(PortSpec("svg", VECTOR_SVG),),
    )

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        fill = str(params.get("fill", "#000000"))
        if not (
            fill.startswith("#")
            and len(fill) in (4, 7)
            and all(character in "0123456789abcdefABCDEF" for character in fill[1:])
        ):
            raise ModuleError(f"fill must be a #rgb or #rrggbb hex color, got {fill!r}")
        root = _parse_svg(inputs["svg"], "input")
        for child in root:
            if child.tag in (f"{{{_SVG_NS}}}g", f"{{{_SVG_NS}}}path"):
                child.set("fill", fill)
        return {"svg": ModuleResult(type=VECTOR_SVG, data=_serialize_svg(root))}


class SvgMergeModule:
    """Stack two SVGs: 'under' first, 'over' on top. Canvas comes from 'under'.

    N-way merges compose as a binary tree (ADR 0009).
    """

    manifest = ModuleManifest(
        name="svg.merge",
        version="1.0",
        description="Stack two SVGs (under, over) on the under-canvas",
        inputs=(PortSpec("under", VECTOR_SVG), PortSpec("over", VECTOR_SVG)),
        outputs=(PortSpec("svg", VECTOR_SVG),),
    )

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        under = _parse_svg(inputs["under"], "under")
        over = _parse_svg(inputs["over"], "over")
        for child in list(over):
            if child.tag == f"{{{_SVG_NS}}}metadata":
                continue
            under.append(child)
        return {"svg": ModuleResult(type=VECTOR_SVG, data=_serialize_svg(under))}
