"""Core raster modules: PIL-based, raster/png in and out.

Each preserves the payload encoding (PNG bytes) so modules chain freely.
`image.downsample` is the draft-aware pipeline-boundary module (ADR 0008).
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageOps

from ..modules import ModuleError, ModuleManifest, ModuleResult, PortSpec

RASTER_PNG = "raster/png"


def _decode(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data))
    except Exception as exc:
        raise ModuleError(f"could not decode PNG input: {exc}") from exc


def _flatten(image: Image.Image) -> Image.Image:
    has_alpha = "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info)
    if not has_alpha:
        return image
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, image.convert("RGBA"))


def _encode(image: Image.Image) -> ModuleResult:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return ModuleResult(type=RASTER_PNG, data=buffer.getvalue())


def _float_param(params: dict[str, Any], name: str, default: float) -> float:
    try:
        return float(params.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ModuleError(f"invalid {name!r}: {params.get(name)!r}") from exc


def _int_param(params: dict[str, Any], name: str, default: int) -> int:
    try:
        return int(params.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ModuleError(f"invalid {name!r}: {params.get(name)!r}") from exc


def _single_image_manifest(name: str, description: str) -> ModuleManifest:
    return ModuleManifest(
        name=name,
        version="1.0",
        description=description,
        inputs=(PortSpec("image", RASTER_PNG),),
        outputs=(PortSpec("image", RASTER_PNG),),
    )


class CropModule:
    """Crop to a pixel rectangle. Changes canvas geometry."""

    manifest = _single_image_manifest(
        "image.crop", "Crop to a pixel rectangle (x, y, width, height)"
    )

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        image = _decode(inputs["image"])
        x = _int_param(params, "x", 0)
        y = _int_param(params, "y", 0)
        width = _int_param(params, "width", image.width - x)
        height = _int_param(params, "height", image.height - y)
        if width <= 0 or height <= 0:
            raise ModuleError(f"crop size must be positive, got {width}x{height}")
        if x < 0 or y < 0 or x + width > image.width or y + height > image.height:
            raise ModuleError(
                f"crop rectangle ({x},{y},{width},{height}) exceeds image bounds "
                f"{image.width}x{image.height}"
            )
        return {"image": _encode(image.crop((x, y, x + width, y + height)))}


class RotateModule:
    """Rotate counter-clockwise by degrees; canvas expands to fit, white fill."""

    manifest = _single_image_manifest("image.rotate", "Rotate counter-clockwise (degrees)")

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        image = _flatten(_decode(inputs["image"])).convert("RGB")
        angle = _float_param(params, "angle", 0.0)
        rotated = image.rotate(angle, expand=True, fillcolor=(255, 255, 255))
        return {"image": _encode(rotated)}


class LevelsModule:
    """Linear levels: map [black, white] to [0, 255] with gamma. Preserves geometry."""

    manifest = _single_image_manifest(
        "image.levels", "Levels adjustment: black point, white point, gamma"
    )

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        image = _flatten(_decode(inputs["image"])).convert("RGB")
        black = _int_param(params, "black", 0)
        white = _int_param(params, "white", 255)
        gamma = _float_param(params, "gamma", 1.0)
        if not 0 <= black < white <= 255:
            raise ModuleError(f"need 0 <= black < white <= 255, got black={black} white={white}")
        if gamma <= 0:
            raise ModuleError(f"gamma must be positive, got {gamma}")

        scale = 255.0 / (white - black)
        table = [
            round(255.0 * (max(0.0, min(1.0, (v - black) * scale / 255.0)) ** (1.0 / gamma)))
            for v in range(256)
        ]
        return {"image": _encode(image.point(table * 3))}


class ThresholdModule:
    """Binarize: gray > level becomes white, else black. The one-way door."""

    manifest = _single_image_manifest("image.threshold", "Binarize at a gray level (0-255)")

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        image = _flatten(_decode(inputs["image"])).convert("L")
        level = _int_param(params, "level", 128)
        if not 0 <= level <= 255:
            raise ModuleError(f"level must be in [0, 255], got {level}")
        return {"image": _encode(image.point(lambda v: 255 if v > level else 0))}


class InvertModule:
    """Invert every channel. Preserves geometry."""

    manifest = _single_image_manifest("image.invert", "Invert colors (per-channel)")

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        image = _flatten(_decode(inputs["image"])).convert("RGB")
        return {"image": _encode(ImageOps.invert(image))}


class DownsampleModule:
    """Draft-aware pipeline-boundary module (ADR 0008).

    Identity at full quality; in draft, shrinks so the longest side is at
    most `max_dimension` (default 512). Never upscales.
    """

    manifest = _single_image_manifest(
        "image.downsample", "Identity at full quality; downsample to max_dimension in draft"
    )

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        if not draft:
            return {"image": ModuleResult(type=RASTER_PNG, data=inputs["image"])}
        image = _decode(inputs["image"])
        max_dimension = _int_param(params, "max_dimension", 512)
        if max_dimension <= 0:
            raise ModuleError(f"max_dimension must be positive, got {max_dimension}")
        if max(image.size) <= max_dimension:
            return {"image": ModuleResult(type=RASTER_PNG, data=inputs["image"])}
        shrunk = ImageOps.contain(image, (max_dimension, max_dimension))
        return {"image": _encode(shrunk)}
