"""Color separation modules: posterize, colormask, svg colorize/merge."""

import io

import pytest
from PIL import Image

from formshift_server.core.color import (
    ColorMaskModule,
    PosterizeModule,
    SvgColorizeModule,
    SvgMergeModule,
)
from formshift_server.modules import ModuleError

SIMPLE_SVG = (
    b'<?xml version="1.0"?>'
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<g fill="#000000"><path d="M0 0h10v10H0z"/></g></svg>'
)


def four_color_png(size: int = 40) -> bytes:
    """Four solid quadrants: red, green, blue, white."""
    image = Image.new("RGB", (size, size), "white")
    half = size // 2
    for x in range(size):
        for y in range(size):
            if x < half and y < half:
                image.putpixel((x, y), (255, 0, 0))
            elif x >= half and y < half:
                image.putpixel((x, y), (0, 255, 0))
            elif x < half:
                image.putpixel((x, y), (0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_posterize_produces_palette_png_with_n_colors() -> None:
    result = PosterizeModule().run({"image": four_color_png()}, {"colors": 4})
    image = Image.open(io.BytesIO(result["image"].data))
    assert image.mode == "P"
    colors = image.getcolors(maxcolors=256)
    assert colors is not None and len(colors) == 4


def test_posterize_validates_color_count() -> None:
    with pytest.raises(ModuleError, match="colors"):
        PosterizeModule().run({"image": four_color_png()}, {"colors": 1})


def test_colormask_extracts_one_color_region() -> None:
    posterized = PosterizeModule().run({"image": four_color_png()}, {"colors": 4})["image"].data
    mask_bytes = ColorMaskModule().run({"image": posterized}, {"index": 0})["mask"].data
    mask = Image.open(io.BytesIO(mask_bytes))
    assert mask.mode == "L"
    histogram = mask.histogram()
    black, white = histogram[0], histogram[255]
    assert black + white == 40 * 40  # strictly binary
    assert black == 20 * 20  # exactly one quadrant


def test_colormask_all_indices_partition_the_image() -> None:
    posterized = PosterizeModule().run({"image": four_color_png()}, {"colors": 4})["image"].data
    total_black = 0
    for index in range(4):
        mask_bytes = ColorMaskModule().run({"image": posterized}, {"index": index})["mask"].data
        total_black += Image.open(io.BytesIO(mask_bytes)).histogram()[0]
    assert total_black == 40 * 40  # masks are disjoint and cover everything


def test_colormask_rejects_non_palette_input() -> None:
    with pytest.raises(ModuleError, match="palette-mode"):
        ColorMaskModule().run({"image": four_color_png()}, {"index": 0})


def test_colormask_rejects_unused_index() -> None:
    posterized = PosterizeModule().run({"image": four_color_png()}, {"colors": 4})["image"].data
    with pytest.raises(ModuleError, match="not present"):
        ColorMaskModule().run({"image": posterized}, {"index": 200})


def test_svg_colorize_sets_fill() -> None:
    result = SvgColorizeModule().run({"svg": SIMPLE_SVG}, {"fill": "#ff0000"})
    assert b'fill="#ff0000"' in result["svg"].data


def test_svg_colorize_validates_hex() -> None:
    with pytest.raises(ModuleError, match="hex color"):
        SvgColorizeModule().run({"svg": SIMPLE_SVG}, {"fill": "red"})


def test_svg_merge_stacks_over_on_under() -> None:
    red = SvgColorizeModule().run({"svg": SIMPLE_SVG}, {"fill": "#ff0000"})["svg"].data
    blue = SvgColorizeModule().run({"svg": SIMPLE_SVG}, {"fill": "#0000ff"})["svg"].data
    merged = SvgMergeModule().run({"under": red, "over": blue}, {})["svg"].data
    assert b'fill="#ff0000"' in merged and b'fill="#0000ff"' in merged
    # over comes after under in document order (paints on top)
    assert merged.index(b"#ff0000") < merged.index(b"#0000ff")


def test_svg_merge_rejects_garbage() -> None:
    with pytest.raises(ModuleError, match="parse"):
        SvgMergeModule().run({"under": b"not svg", "over": SIMPLE_SVG}, {})
