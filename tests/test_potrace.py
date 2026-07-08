"""potrace module against the real binary, plus the full HTTP round trip.

These tests skip when no potrace binary is available (CI without it); the
M0 exit condition requires them to run and pass on the dev machine.
"""

import asyncio
import io
from typing import Any

import httpx
import pytest
from PIL import Image

from formshift_server.core.potrace import PotraceModule, find_potrace
from formshift_server.modules import ModuleError

requires_potrace = pytest.mark.skipif(find_potrace() is None, reason="potrace binary not available")


def make_png(size: int = 64, transparent: bool = False) -> bytes:
    """A black circle on white (or transparent) background."""
    mode = "RGBA" if transparent else "RGB"
    background = (255, 255, 255, 0) if transparent else (255, 255, 255)
    image = Image.new(mode, (size, size), background)
    for x in range(size):
        for y in range(size):
            if (x - size // 2) ** 2 + (y - size // 2) ** 2 < (size // 3) ** 2:
                image.putpixel((x, y), (0, 0, 0, 255) if transparent else (0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@requires_potrace
def test_traces_circle_to_svg() -> None:
    result = PotraceModule().run({"image": make_png()}, {})
    svg = result["svg"].data
    assert svg.startswith(b"<?xml")
    assert b"<svg" in svg and b"<path" in svg
    assert result["svg"].type == "vector/svg"


@requires_potrace
def test_transparent_background_composites_to_white() -> None:
    """Transparency must not trace as solid black (alpha composited onto white)."""
    svg_opaque = PotraceModule().run({"image": make_png()}, {})["svg"].data
    svg_transparent = PotraceModule().run({"image": make_png(transparent=True)}, {})["svg"].data
    # Both should produce a comparable path count (one circle), not a full-canvas blob.
    assert svg_transparent.count(b"<path") == svg_opaque.count(b"<path")


@requires_potrace
def test_blacklevel_out_of_range_is_module_error() -> None:
    with pytest.raises(ModuleError, match="blacklevel"):
        PotraceModule().run({"image": make_png()}, {"blacklevel": 1.5})


@requires_potrace
def test_garbage_png_is_module_error() -> None:
    with pytest.raises(ModuleError, match="decode"):
        PotraceModule().run({"image": b"not a png"}, {})


@requires_potrace
@pytest.mark.anyio
async def test_end_to_end_png_to_svg_over_http(client: httpx.AsyncClient) -> None:
    """The M0 exit condition: PNG in, SVG out, entirely through the HTTP API."""
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads",
        params={"type": "raster/png"},
        content=make_png(),
    )
    payload_id = upload.json()["id"]

    graph: dict[str, Any] = {
        "nodes": [{"id": "trace", "module": "potrace.trace", "params": {"blacklevel": 0.5}}],
        "edges": [],
        "bindings": [{"payload": payload_id, "node": "trace", "port": "image"}],
        "outputs": [{"node": "trace", "port": "svg"}],
    }
    submit = await client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph})
    assert submit.status_code == 201
    job_id = submit.json()["id"]

    for _ in range(200):
        doc = (await client.get(f"/v1/sessions/{session_id}/jobs/{job_id}")).json()
        if doc["status"] in {"completed", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.05)
    assert doc["status"] == "completed", doc

    output = doc["outputs"][0]
    assert output["type"] == "vector/svg"
    svg = await client.get(f"/v1/sessions/{session_id}/payloads/{output['payload']}")
    assert b"<svg" in svg.content and b"<path" in svg.content
