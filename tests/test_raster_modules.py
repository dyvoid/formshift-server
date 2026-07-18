"""Core raster modules: behavior, geometry, and draft awareness (ADR 0008)."""

import io

import pytest
from PIL import Image

from formshift_server.core.raster import (
    CropModule,
    DownsampleModule,
    InvertModule,
    LevelsModule,
    RotateModule,
    ThresholdModule,
)
from formshift_server.modules import ModuleError


def png(width: int = 100, height: int = 80, color: tuple[int, int, int] = (128, 128, 128)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_crop_returns_requested_rectangle() -> None:
    result = CropModule().run({"image": png()}, {"x": 10, "y": 20, "width": 30, "height": 40})
    assert decode(result["image"].data).size == (30, 40)


def test_crop_out_of_bounds_is_module_error() -> None:
    with pytest.raises(ModuleError, match="exceeds image bounds"):
        CropModule().run({"image": png()}, {"x": 90, "y": 0, "width": 30, "height": 10})


def test_rotate_90_swaps_dimensions() -> None:
    result = RotateModule().run({"image": png(100, 80)}, {"angle": 90})
    assert decode(result["image"].data).size == (80, 100)


def test_rotate_45_expands_canvas() -> None:
    result = RotateModule().run({"image": png(100, 100)}, {"angle": 45})
    width, height = decode(result["image"].data).size
    assert width > 100 and height > 100


def test_levels_stretches_midtone() -> None:
    result = LevelsModule().run({"image": png(color=(128, 128, 128))}, {"black": 100, "white": 156})
    pixel = decode(result["image"].data).getpixel((0, 0))
    assert pixel == (128, 128, 128)  # midpoint of [100,156] maps back to 128

    darker = LevelsModule().run({"image": png(color=(100, 100, 100))}, {"black": 100, "white": 156})
    assert decode(darker["image"].data).getpixel((0, 0)) == (0, 0, 0)


def test_levels_validates_range() -> None:
    with pytest.raises(ModuleError, match="black < white"):
        LevelsModule().run({"image": png()}, {"black": 200, "white": 100})


def test_threshold_binarizes() -> None:
    result = ThresholdModule().run({"image": png(color=(128, 128, 128))}, {"level": 100})
    assert decode(result["image"].data).getpixel((0, 0)) == 255
    result = ThresholdModule().run({"image": png(color=(128, 128, 128))}, {"level": 200})
    assert decode(result["image"].data).getpixel((0, 0)) == 0


def test_invert_flips_each_channel() -> None:
    result = InvertModule().run({"image": png(color=(10, 20, 30))}, {})
    assert decode(result["image"].data).getpixel((0, 0)) == (245, 235, 225)


def test_invert_is_self_inverse() -> None:
    data = png(color=(123, 200, 7))
    once = InvertModule().run({"image": data}, {})["image"].data
    twice = InvertModule().run({"image": once}, {})["image"].data
    assert decode(twice).getpixel((0, 0)) == (123, 200, 7)


def test_invert_preserves_geometry() -> None:
    result = InvertModule().run({"image": png(100, 80)}, {})
    assert decode(result["image"].data).size == (100, 80)


def test_invert_flattens_transparency_before_inverting() -> None:
    # Transparent must composite to white first, then invert to black —
    # not drop alpha and read as already-black.
    result = InvertModule().run({"image": transparent_png()}, {})
    assert decode(result["image"].data).getpixel((10, 10)) == (0, 0, 0)


def transparent_png(width: int = 20, height: int = 20) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_transparency_flattens_to_white_not_black() -> None:
    data = transparent_png()
    for module in (RotateModule(), LevelsModule(), ThresholdModule()):
        result = module.run({"image": data}, {})
        pixel = decode(result["image"].data).convert("L").getpixel((10, 10))
        assert pixel == 255, type(module).__name__


def test_downsample_is_identity_at_full_quality() -> None:
    data = png(1000, 800)
    result = DownsampleModule().run({"image": data}, {"max_dimension": 100}, draft=False)
    assert result["image"].data == data  # byte-identical passthrough


def test_downsample_shrinks_in_draft() -> None:
    result = DownsampleModule().run({"image": png(1000, 800)}, {"max_dimension": 100}, draft=True)
    width, height = decode(result["image"].data).size
    assert max(width, height) == 100
    assert (width, height) == (100, 80)  # aspect preserved


def test_downsample_never_upscales() -> None:
    data = png(50, 40)
    result = DownsampleModule().run({"image": data}, {"max_dimension": 100}, draft=True)
    assert result["image"].data == data
