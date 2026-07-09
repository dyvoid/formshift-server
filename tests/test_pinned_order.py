"""Pinned-order output groups (ADR 0014): progressive rendering's second path.

The overlap scenario from the design doc: outputs that deliberately stack
(underbase beneath ink layers) must reach the client in declared order, not
completion order. Every test builds a fan-out where the FIRST-declared output
finishes LAST, so completion order and pinned order genuinely disagree.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from formshift_server.app import create_app
from formshift_server.config import ServerConfig
from formshift_server.modules import ModuleRegistry

from .conftest import TEST_TOKEN
from .helpers import TEXT, DelayModule, UpperModule

pytestmark = pytest.mark.anyio

SLOW = 0.3  # seconds; comfortably longer than the fast branch's ~instant run


def _registry() -> ModuleRegistry:
    registry = ModuleRegistry()
    registry.register(DelayModule())
    registry.register(UpperModule())
    return registry


@pytest.fixture
def app(config: ServerConfig) -> FastAPI:
    return create_app(config, registry=_registry())


@pytest.fixture
async def client(app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as client:
        yield client


def _fanout_graph(
    payload_id: str,
    outputs: list[dict[str, str]],
    groups: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """One payload feeding an (intentionally) slow branch and a fast branch."""
    graph: dict[str, Any] = {
        "nodes": [
            {"id": "slow", "module": "test.delay", "params": {"seconds": SLOW}},
            {"id": "fast", "module": "test.upper"},
        ],
        "bindings": [
            {"payload": payload_id, "node": "slow", "port": "text"},
            {"payload": payload_id, "node": "fast", "port": "text"},
        ],
        "outputs": outputs,
    }
    if groups is not None:
        graph["groups"] = groups
    return graph


def _output_events(app: FastAPI, session_id: str) -> list[dict[str, Any]]:
    manager = app.state.managers[session_id]
    return [e.data for e in manager.events.since(0) if e.type == "job.output"]


async def test_completion_order_still_streams_fast_first(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Control: without a pinned group, the fast branch emits before the slow one."""
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads", params={"type": TEXT}, content=b"ink"
    )
    graph = _fanout_graph(
        upload.json()["id"],
        outputs=[{"node": "slow", "port": "text"}, {"node": "fast", "port": "text"}],
    )
    submit = await client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph})
    assert submit.status_code == 201, submit.text
    job_id = submit.json()["id"]
    while (await client.get(f"/v1/sessions/{session_id}/jobs/{job_id}")).json()[
        "status"
    ] not in {"completed", "failed"}:
        await asyncio.sleep(0.02)

    events = _output_events(app, session_id)
    assert [e["node"] for e in events] == ["fast", "slow"]  # completion order
    assert all("group" not in e for e in events)


async def test_pinned_group_emits_in_declared_order(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Exit condition: first-declared output finishes last, yet emits first."""
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads", params={"type": TEXT}, content=b"ink"
    )
    graph = _fanout_graph(
        upload.json()["id"],
        outputs=[
            {"node": "slow", "port": "text", "group": "seps"},  # underbase: must land first
            {"node": "fast", "port": "text", "group": "seps"},
        ],
        groups=[{"id": "seps", "order": "pinned"}],
    )
    submit = await client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph})
    assert submit.status_code == 201, submit.text
    job_id = submit.json()["id"]
    while True:
        doc = (await client.get(f"/v1/sessions/{session_id}/jobs/{job_id}")).json()
        if doc["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.02)

    assert doc["status"] == "completed", doc
    events = _output_events(app, session_id)
    assert [e["node"] for e in events] == ["slow", "fast"]  # declared, not completion, order
    assert [e["group"] for e in events] == ["seps", "seps"]
    # The terminal job document lists outputs in the same pinned order.
    assert [o["node"] for o in doc["outputs"]] == ["slow", "fast"]


async def test_pinned_groups_do_not_block_each_other(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads", params={"type": TEXT}, content=b"ink"
    )
    graph = _fanout_graph(
        upload.json()["id"],
        outputs=[
            {"node": "slow", "port": "text", "group": "a"},
            {"node": "fast", "port": "text", "group": "b"},
        ],
        groups=[{"id": "a", "order": "pinned"}, {"id": "b", "order": "pinned"}],
    )
    submit = await client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph})
    assert submit.status_code == 201, submit.text
    job_id = submit.json()["id"]
    while (await client.get(f"/v1/sessions/{session_id}/jobs/{job_id}")).json()[
        "status"
    ] != "completed":
        await asyncio.sleep(0.02)

    events = _output_events(app, session_id)
    # Group b's only member is fast: nothing in group a may hold it back.
    assert [e["node"] for e in events] == ["fast", "slow"]


async def test_completion_group_streams_but_carries_group_id(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads", params={"type": TEXT}, content=b"ink"
    )
    graph = _fanout_graph(
        upload.json()["id"],
        outputs=[
            {"node": "slow", "port": "text", "group": "g"},
            {"node": "fast", "port": "text", "group": "g"},
        ],
        groups=[{"id": "g", "order": "completion"}],
    )
    submit = await client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph})
    assert submit.status_code == 201
    job_id = submit.json()["id"]
    while (await client.get(f"/v1/sessions/{session_id}/jobs/{job_id}")).json()[
        "status"
    ] != "completed":
        await asyncio.sleep(0.02)

    events = _output_events(app, session_id)
    assert [e["node"] for e in events] == ["fast", "slow"]  # still completion order
    assert [e["group"] for e in events] == ["g", "g"]


@pytest.mark.parametrize(
    ("outputs", "groups", "expected_error"),
    [
        (
            [{"node": "fast", "port": "text", "group": "ghost"}],
            [],
            "undeclared group",
        ),
        (
            [{"node": "fast", "port": "text", "group": "g"}],
            [{"id": "g", "order": "alphabetical"}],
            "unknown order",
        ),
        (
            [{"node": "fast", "port": "text", "group": "g"}],
            [{"id": "g", "order": "pinned"}, {"id": "g", "order": "pinned"}],
            "duplicate output group",
        ),
    ],
)
async def test_group_validation_rejected_with_422(
    client: httpx.AsyncClient,
    outputs: list[dict[str, str]],
    groups: list[dict[str, str]],
    expected_error: str,
) -> None:
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads", params={"type": TEXT}, content=b"ink"
    )
    graph = _fanout_graph(upload.json()["id"], outputs=outputs, groups=groups)
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] == "fast"]
    graph["bindings"] = [b for b in graph["bindings"] if b["node"] == "fast"]
    response = await client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph})
    assert response.status_code == 422
    assert any(expected_error in e for e in response.json()["detail"])
