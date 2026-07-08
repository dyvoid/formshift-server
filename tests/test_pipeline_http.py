"""M1 exit conditions at the HTTP level, with the real core modules.

- Reordering a mid-stack node recomputes only what is downstream of the change.
- Draft runs honor the boundary downsample and never share cache entries with
  full-quality runs.
"""

import asyncio
import io
from typing import Any

import httpx
import pytest
from PIL import Image

pytestmark = pytest.mark.anyio


def make_png(width: int = 200, height: int = 160) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    for x in range(width // 4, width // 2):
        for y in range(height // 4, height // 2):
            image.putpixel((x, y), (40, 40, 40))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def chain_graph(payload_id: str, order: list[tuple[str, str, dict[str, Any]]]) -> dict[str, Any]:
    """A linear chain of single-image modules in the given (id, module, params) order."""
    nodes = [{"id": nid, "module": module, "params": params} for nid, module, params in order]
    edges = [
        {
            "from_node": order[i][0],
            "from_port": "image",
            "to_node": order[i + 1][0],
            "to_port": "image",
        }
        for i in range(len(order) - 1)
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "bindings": [{"payload": payload_id, "node": order[0][0], "port": "image"}],
        "outputs": [{"node": order[-1][0], "port": "image"}],
    }


async def _run_job(
    client: httpx.AsyncClient, session_id: str, graph: dict[str, Any], draft: bool = False
) -> dict[str, Any]:
    submit = await client.post(
        f"/v1/sessions/{session_id}/jobs", json={"graph": graph, "draft": draft}
    )
    assert submit.status_code == 201, submit.text
    job_id = submit.json()["id"]
    doc: dict[str, Any]
    for _ in range(400):
        doc = (await client.get(f"/v1/sessions/{session_id}/jobs/{job_id}")).json()
        if doc["status"] in {"completed", "failed", "cancelled"}:
            return doc
        await asyncio.sleep(0.025)
    raise AssertionError(f"job did not finish: {doc}")


async def test_reorder_recomputes_only_downstream(client: httpx.AsyncClient) -> None:
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads",
        params={"type": "raster/png"},
        content=make_png(),
    )
    payload_id = upload.json()["id"]

    levels = ("lv", "image.levels", {"black": 10, "white": 240})
    threshold = ("th", "image.threshold", {"level": 100})
    crop = ("cr", "image.crop", {"x": 0, "y": 0, "width": 150, "height": 120})

    # First run: everything executes.
    doc1 = await _run_job(client, session_id, chain_graph(payload_id, [crop, levels, threshold]))
    assert doc1["status"] == "completed"

    # Swap the two downstream nodes: crop's result must come from cache.
    doc2 = await _run_job(client, session_id, chain_graph(payload_id, [crop, threshold, levels]))
    assert doc2["status"] == "completed"

    # Third run repeats the second ordering: everything must be cached.
    doc3 = await _run_job(client, session_id, chain_graph(payload_id, [crop, threshold, levels]))
    assert doc3["status"] == "completed"

    # Verify via the SSE event log (bounded read: job already terminal).
    events = await _collect_events(client, session_id)
    flags = _node_cached_by_job(events)
    job2_flags = flags[doc2["id"]]
    assert job2_flags["cr"] is True  # upstream of the swap: cache hit
    assert job2_flags["th"] is False  # reordered: recomputed
    assert job2_flags["lv"] is False  # reordered: recomputed
    job3_flags = flags[doc3["id"]]
    assert all(job3_flags.values())  # identical rerun: fully cached


async def test_draft_and_full_quality_do_not_share_cache(client: httpx.AsyncClient) -> None:
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads",
        params={"type": "raster/png"},
        content=make_png(1200, 900),
    )
    payload_id = upload.json()["id"]

    graph = chain_graph(
        payload_id,
        [
            ("ds", "image.downsample", {"max_dimension": 100}),
            ("th", "image.threshold", {"level": 100}),
        ],
    )

    draft_doc = await _run_job(client, session_id, graph, draft=True)
    full_doc = await _run_job(client, session_id, graph, draft=False)
    assert draft_doc["status"] == "completed" and full_doc["status"] == "completed"

    async def output_size(doc: dict[str, Any]) -> tuple[int, int]:
        payload = doc["outputs"][0]["payload"]
        data = (await client.get(f"/v1/sessions/{session_id}/payloads/{payload}")).content
        image = Image.open(io.BytesIO(data))
        return image.size

    assert await output_size(draft_doc) == (100, 75)  # boundary downsample applied
    assert await output_size(full_doc) == (1200, 900)  # full quality untouched

    events = await _collect_events(client, session_id)
    flags = _node_cached_by_job(events)
    # The full-quality run must not reuse draft results despite identical graphs.
    assert flags[full_doc["id"]]["ds"] is False
    assert flags[full_doc["id"]]["th"] is False


async def _collect_events(client: httpx.AsyncClient, session_id: str) -> list[dict[str, Any]]:
    """Read the session's event log via the app under test (all jobs terminal).

    The SSE endpoint's stream is unbounded, and httpx's ASGITransport buffers
    whole responses, so the log is read directly from the JobManager instead;
    the SSE wire path itself is covered by the live-server test in
    test_jobs_api.py.
    """
    transport = client._transport
    assert isinstance(transport, httpx.ASGITransport)
    manager = transport.app.state.managers[session_id]  # type: ignore[attr-defined]
    return [{"type": e.type, **e.data} for e in manager.events.since(0)]


def _node_cached_by_job(events: list[dict[str, Any]]) -> dict[str, dict[str, bool]]:
    flags: dict[str, dict[str, bool]] = {}
    for event in events:
        if event["type"] == "node.completed":
            flags.setdefault(event["job"], {})[event["node"]] = event["cached"]
    return flags
