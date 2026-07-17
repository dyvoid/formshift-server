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

from PIL import Image

from ..modules import ModuleError, ModuleManifest, ModuleResult, PortSpec
from .raster import RASTER_PNG, _decode, _encode, _flatten, _int_param

VECTOR_SVG = "vector/svg"

_SVG_NS = "http://www.w3.org/2000/svg"


class PosterizeModule:
    """Quantize to N flat colors. Output is a palette-mode PNG; the palette
    (index -> RGB) is readable by any PNG decoder, which is how clients and
    the colormask module learn the color of each index."""

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
        colors = _int_param(params, "colors", 8)
        if not 2 <= colors <= 256:
            raise ModuleError(f"colors must be in [2, 256], got {colors}")
        image = _flatten(_decode(inputs["image"])).convert("RGB")
        quantized = image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        return {"image": _encode(quantized)}


class ColorMaskModule:
    """Extract one palette index from a posterized image as a binary mask
    (index pixels black, everything else white — ready for tracing)."""

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
        used_indices = {value for _, value in image.getcolors(maxcolors=256) or []}
        if not 0 <= index < 256:
            raise ModuleError(f"index must be in [0, 256), got {index}")
        if index not in used_indices:
            raise ModuleError(
                f"index {index} not present in image (used indices: {sorted(used_indices)})"
            )
        # point() with an explicit target mode maps raw palette indices through
        # the LUT, sidestepping palette color interpretation entirely.
        lut = [255] * 256
        lut[index] = 0
        mask = image.point(lut, mode="L")
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
