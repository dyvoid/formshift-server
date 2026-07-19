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


def test_colormask_rejects_out_of_range_index() -> None:
    posterized = PosterizeModule().run({"image": four_color_png()}, {"colors": 4})["image"].data
    for index in (-1, 256):
        with pytest.raises(ModuleError, match=r"\[0, 256\)"):
            ColorMaskModule().run({"image": posterized}, {"index": index})


def _unused_index_posterized() -> bytes:
    """Posterize with an explicit palette whose last entry no pixel maps to."""
    # The image's four colors are exact entries, so the fifth maps to nothing.
    palette = ["#ff0000", "#00ff00", "#0000ff", "#ffffff", "#800080"]
    return PosterizeModule().run({"image": four_color_png()}, {"palette": palette})["image"].data


def test_colormask_unused_index_yields_empty_mask() -> None:
    """ADR 0022: an in-range but unused palette index selects nothing."""
    posterized = _unused_index_posterized()
    assert 4 not in {value for _, value in Image.open(io.BytesIO(posterized)).getcolors(256) or []}
    mask_bytes = ColorMaskModule().run({"image": posterized}, {"index": 4})["mask"].data
    mask = Image.open(io.BytesIO(mask_bytes))
    assert mask.mode == "L"
    assert mask.histogram()[255] == 40 * 40  # all white: nothing selected


def test_colormask_grow_on_unused_index_stays_empty() -> None:
    posterized = _unused_index_posterized()
    mask_bytes = ColorMaskModule().run({"image": posterized}, {"index": 4, "grow": 2})["mask"].data
    assert Image.open(io.BytesIO(mask_bytes)).histogram()[255] == 40 * 40


def test_svg_colorize_sets_fill() -> None:
    result = SvgColorizeModule().run({"svg": SIMPLE_SVG}, {"fill": "#ff0000"})
    assert b'fill="#ff0000"' in result["svg"].data


def test_svg_colorize_validates_hex() -> None:
    for fill in ("red", "#zzz", "#12345g", "#12345"):
        with pytest.raises(ModuleError, match="hex color"):
            SvgColorizeModule().run({"svg": SIMPLE_SVG}, {"fill": fill})


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


# --- explicit palette (ADR 0020) ---


def rare_color_png(size: int = 40) -> bytes:
    """Mostly red, with a 2x2 green patch median-cut would absorb."""
    image = Image.new("RGB", (size, size), (255, 0, 0))
    for x in range(2):
        for y in range(2):
            image.putpixel((x, y), (0, 200, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_palette_preserves_rare_color_and_plte_order() -> None:
    result = PosterizeModule().run(
        {"image": rare_color_png()}, {"palette": ["#ff0000", "#00c800"]}
    )
    image = Image.open(io.BytesIO(result["image"].data))
    assert image.mode == "P"
    palette = image.getpalette()
    assert palette is not None
    assert palette[:6] == [255, 0, 0, 0, 200, 0]  # PLTE in supplied order
    histogram = image.histogram()
    assert histogram[1] == 4  # the 2x2 green patch survived, at index 1
    assert histogram[0] == 40 * 40 - 4


def test_palette_maps_pixels_to_nearest_entry() -> None:
    image = Image.new("RGB", (4, 4), (250, 10, 10))  # near-red, not exact
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    result = PosterizeModule().run(
        {"image": buffer.getvalue()}, {"palette": ["#0000ff", "#ff0000"]}
    )
    output = Image.open(io.BytesIO(result["image"].data))
    assert output.histogram()[1] == 16  # everything lands on the red entry


def test_palette_and_colors_are_mutually_exclusive() -> None:
    with pytest.raises(ModuleError, match="mutually exclusive"):
        PosterizeModule().run(
            {"image": four_color_png()}, {"palette": ["#ff0000", "#00ff00"], "colors": 4}
        )


def test_palette_validates_entries() -> None:
    for palette in (
        ["#ff0000"],  # too short
        ["#ff0000", "red"],  # not hex
        ["#ff0000", "#f00"],  # #rgb shorthand rejected
        ["#ff0000", "#ff0000"],  # duplicate
        "#ff0000",  # not a list
    ):
        with pytest.raises(ModuleError, match="palette"):
            PosterizeModule().run({"image": four_color_png()}, {"palette": palette})


# --- colormask grow (ADR 0021) ---


def test_grow_dilates_mask_and_overlaps_neighbor() -> None:
    posterized = PosterizeModule().run({"image": four_color_png()}, {"colors": 4})["image"].data
    grown_black = []
    for index in range(4):
        mask_bytes = (
            ColorMaskModule().run({"image": posterized}, {"index": index, "grow": 2})["mask"].data
        )
        mask = Image.open(io.BytesIO(mask_bytes))
        assert mask.mode == "L"
        histogram = mask.histogram()
        assert histogram[0] + histogram[255] == 40 * 40  # still strictly binary
        grown_black.append(histogram[0])
    # each quadrant grew from 20x20 to (20+2)x(20+2), clipped at the canvas corner
    assert all(black == 22 * 22 for black in grown_black)
    # grown masks are no longer disjoint: they overlap at the seams
    assert sum(grown_black) > 40 * 40


def test_grow_zero_and_absent_match_existing_behavior() -> None:
    posterized = PosterizeModule().run({"image": four_color_png()}, {"colors": 4})["image"].data
    absent = ColorMaskModule().run({"image": posterized}, {"index": 0})["mask"].data
    zero = ColorMaskModule().run({"image": posterized}, {"index": 0, "grow": 0})["mask"].data
    assert absent == zero


def test_grow_rejects_negative_and_non_integer() -> None:
    posterized = PosterizeModule().run({"image": four_color_png()}, {"colors": 4})["image"].data
    for grow in (-1, 1.5, "2", True):
        with pytest.raises(ModuleError, match="grow"):
            ColorMaskModule().run({"image": posterized}, {"index": 0, "grow": grow})
