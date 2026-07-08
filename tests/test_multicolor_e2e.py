"""M2 exit: a 16-color trace runs end to end and renders progressively.

Mirrors the real client flow: job 1 posterizes and the client reads the
palette from the result; job 2 submits the full separation graph, whose
posterize node is then a cache hit. Every color layer is a declared output,
so job.output events stream as branches complete (the disjoint progressive
path — posterize masks partition the image, layers cannot overlap).
"""

import asyncio
import io
from typing import Any, cast

import httpx
import pytest
from PIL import Image

from formshift_server.core.potrace import find_potrace

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(find_potrace() is None, reason="potrace binary not available"),
]

COLORS = 16


def sixteen_color_png(cell: int = 60) -> bytes:
    """A 4x4 grid of 16 clearly distinct colors."""
    values = [0, 85, 170, 255]
    image = Image.new("RGB", (cell * 4, cell * 4))
    for i in range(COLORS):
        r, g = divmod(i, 4)
        color = (values[r], values[g], 128 if (i % 2) else 40)
        for x in range(g * cell, (g + 1) * cell):
            for y in range(r * cell, (r + 1) * cell):
                image.putpixel((x, y), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def separation_graph(payload_id: str, palette: dict[int, str]) -> dict[str, Any]:
    """posterize -> per-index (mask -> trace -> colorize) -> binary merge tree."""
    nodes: list[dict[str, Any]] = [
        {"id": "post", "module": "image.posterize", "params": {"colors": COLORS}}
    ]
    edges: list[dict[str, str]] = []
    for index, fill in palette.items():
        nodes += [
            {"id": f"mask{index}", "module": "image.colormask", "params": {"index": index}},
            {"id": f"trace{index}", "module": "potrace.trace", "params": {"blacklevel": 0.5}},
            {"id": f"color{index}", "module": "svg.colorize", "params": {"fill": fill}},
        ]
        edges += [
            {
                "from_node": "post",
                "from_port": "image",
                "to_node": f"mask{index}",
                "to_port": "image",
            },
            {
                "from_node": f"mask{index}",
                "from_port": "mask",
                "to_node": f"trace{index}",
                "to_port": "image",
            },
            {
                "from_node": f"trace{index}",
                "from_port": "svg",
                "to_node": f"color{index}",
                "to_port": "svg",
            },
        ]

    # Binary merge tree over the colorized layers (ADR 0009).
    layer: list[tuple[str, str]] = [(f"color{i}", "svg") for i in palette]
    merge_count = 0
    while len(layer) > 1:
        next_layer: list[tuple[str, str]] = []
        for i in range(0, len(layer) - 1, 2):
            node_id = f"merge{merge_count}"
            merge_count += 1
            nodes.append({"id": node_id, "module": "svg.merge", "params": {}})
            (under_node, under_port), (over_node, over_port) = layer[i], layer[i + 1]
            edges += [
                {
                    "from_node": under_node,
                    "from_port": under_port,
                    "to_node": node_id,
                    "to_port": "under",
                },
                {
                    "from_node": over_node,
                    "from_port": over_port,
                    "to_node": node_id,
                    "to_port": "over",
                },
            ]
            next_layer.append((node_id, "svg"))
        if len(layer) % 2:
            next_layer.append(layer[-1])
        layer = next_layer

    outputs = [{"node": f"color{i}", "port": "svg"} for i in palette]
    outputs.append({"node": layer[0][0], "port": layer[0][1]})
    return {
        "nodes": nodes,
        "edges": edges,
        "bindings": [{"payload": payload_id, "node": "post", "port": "image"}],
        "outputs": outputs,
    }


async def _run_job(
    client: httpx.AsyncClient, session_id: str, graph: dict[str, Any]
) -> dict[str, Any]:
    submit = await client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph})
    assert submit.status_code == 201, submit.text
    job_id = submit.json()["id"]
    doc: dict[str, Any]
    for _ in range(1200):
        doc = (await client.get(f"/v1/sessions/{session_id}/jobs/{job_id}")).json()
        if doc["status"] in {"completed", "failed", "cancelled"}:
            return doc
        await asyncio.sleep(0.025)
    raise AssertionError(f"job did not finish: {doc}")


async def test_sixteen_color_trace_progressive(client: httpx.AsyncClient) -> None:
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads",
        params={"type": "raster/png"},
        content=sixteen_color_png(),
    )
    payload_id = upload.json()["id"]

    # Job 1: posterize alone; the client reads the palette from the result.
    post_graph = {
        "nodes": [{"id": "post", "module": "image.posterize", "params": {"colors": COLORS}}],
        "bindings": [{"payload": payload_id, "node": "post", "port": "image"}],
        "outputs": [{"node": "post", "port": "image"}],
    }
    doc1 = await _run_job(client, session_id, post_graph)
    assert doc1["status"] == "completed"
    posterized = (
        await client.get(f"/v1/sessions/{session_id}/payloads/{doc1['outputs'][0]['payload']}")
    ).content
    image = Image.open(io.BytesIO(posterized))
    assert image.mode == "P"
    raw_palette = image.getpalette()
    assert raw_palette is not None
    colors = cast(list[tuple[int, int]], image.getcolors(maxcolors=256) or [])
    used: list[int] = sorted(index for _, index in colors)
    assert len(used) == COLORS
    palette = {
        index: "#{:02x}{:02x}{:02x}".format(*raw_palette[index * 3 : index * 3 + 3])
        for index in used
    }

    # Job 2: the full separation graph. Its posterize node must be a cache hit.
    doc2 = await _run_job(client, session_id, separation_graph(payload_id, palette))
    assert doc2["status"] == "completed"
    assert len(doc2["outputs"]) == COLORS + 1  # 16 layers + merged result

    merged_ref = doc2["outputs"][-1]
    merged = (
        await client.get(f"/v1/sessions/{session_id}/payloads/{merged_ref['payload']}")
    ).content
    for fill in palette.values():
        assert fill.encode() in merged  # every color layer present in the final SVG

    # Progressive + caching assertions via the event log.
    transport = client._transport
    assert isinstance(transport, httpx.ASGITransport)
    manager = transport.app.state.managers[session_id]  # type: ignore[attr-defined]
    events = [(e.type, e.data) for e in manager.events.since(0)]
    job2 = doc2["id"]

    post_events = [d for t, d in events if t == "node.completed" and d["job"] == job2]
    assert next(d for d in post_events if d["node"] == "post")["cached"] is True

    indexed = [(i, t, d) for i, (t, d) in enumerate(events) if d.get("job") == job2]
    output_indices = [i for i, t, _ in indexed if t == "job.output"]
    node_indices = [i for i, t, _ in indexed if t == "node.completed"]
    assert len(output_indices) == COLORS + 1
    # Streaming, not batch-at-end: the first output event lands well before
    # the last node completes.
    assert output_indices[0] < node_indices[-1]
