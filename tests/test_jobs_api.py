"""Job endpoints and SSE event contract (ADR 0007), using fake modules."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest

from formshift_server.app import create_app
from formshift_server.config import ServerConfig
from formshift_server.modules import ModuleRegistry

from .conftest import TEST_TOKEN
from .helpers import TEXT, ConcatModule, SuffixModule, UpperModule

pytestmark = pytest.mark.anyio


def _fake_registry() -> ModuleRegistry:
    registry = ModuleRegistry()
    registry.register(UpperModule())
    registry.register(SuffixModule())
    registry.register(ConcatModule())
    return registry


@pytest.fixture
async def fake_client(config: ServerConfig) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(config, registry=_fake_registry()))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as client:
        yield client


@pytest.fixture
def live_server(config: ServerConfig) -> Iterator[str]:
    """A real uvicorn server on an OS-assigned port, for streaming tests."""
    import socket
    import threading
    import time

    import uvicorn

    app = create_app(config, registry=_fake_registry())
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "uvicorn failed to start"
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def linear_graph(payload_id: str) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "up", "module": "test.upper"},
            {"id": "suf", "module": "test.suffix", "params": {"suffix": "!"}},
        ],
        "edges": [{"from_node": "up", "from_port": "text", "to_node": "suf", "to_port": "text"}],
        "bindings": [{"payload": payload_id, "node": "up", "port": "text"}],
        "outputs": [{"node": "suf", "port": "text"}],
    }


async def _session_with_payload(
    client: httpx.AsyncClient, data: bytes = b"hello"
) -> tuple[str, str]:
    session_id = (await client.post("/v1/sessions")).json()["id"]
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads", params={"type": TEXT}, content=data
    )
    return session_id, upload.json()["id"]


async def _wait_terminal(
    client: httpx.AsyncClient, session_id: str, job_id: str, timeout: float = 10.0
) -> dict[str, Any]:
    deadline = asyncio.get_event_loop().time() + timeout
    doc: dict[str, Any]
    while True:
        doc = (await client.get(f"/v1/sessions/{session_id}/jobs/{job_id}")).json()
        if doc["status"] in {"completed", "failed", "cancelled"}:
            return doc
        assert asyncio.get_event_loop().time() < deadline, f"job stuck: {doc}"
        await asyncio.sleep(0.02)


async def test_job_runs_and_result_is_a_payload(fake_client: httpx.AsyncClient) -> None:
    session_id, payload_id = await _session_with_payload(fake_client)
    submit = await fake_client.post(
        f"/v1/sessions/{session_id}/jobs", json={"graph": linear_graph(payload_id)}
    )
    assert submit.status_code == 201
    job = await _wait_terminal(fake_client, session_id, submit.json()["id"])

    assert job["status"] == "completed"
    assert len(job["outputs"]) == 1
    output = job["outputs"][0]
    assert output["node"] == "suf" and output["type"] == TEXT

    download = await fake_client.get(f"/v1/sessions/{session_id}/payloads/{output['payload']}")
    assert download.content == b"HELLO!"


async def test_invalid_graph_rejected_with_422_and_errors(fake_client: httpx.AsyncClient) -> None:
    session_id, payload_id = await _session_with_payload(fake_client)
    graph = linear_graph(payload_id)
    graph["nodes"][0]["module"] = "test.nope"
    response = await fake_client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph})
    assert response.status_code == 422
    assert any("unknown module" in e for e in response.json()["detail"])


async def test_unknown_job_404(fake_client: httpx.AsyncClient) -> None:
    session_id, _ = await _session_with_payload(fake_client)
    assert (await fake_client.get(f"/v1/sessions/{session_id}/jobs/nope")).status_code == 404
    assert (await fake_client.delete(f"/v1/sessions/{session_id}/jobs/nope")).status_code == 404


async def test_cancel_is_idempotent_on_terminal_job(fake_client: httpx.AsyncClient) -> None:
    session_id, payload_id = await _session_with_payload(fake_client)
    submit = await fake_client.post(
        f"/v1/sessions/{session_id}/jobs", json={"graph": linear_graph(payload_id)}
    )
    job_id = submit.json()["id"]
    await _wait_terminal(fake_client, session_id, job_id)
    response = await fake_client.delete(f"/v1/sessions/{session_id}/jobs/{job_id}")
    assert response.status_code == 204


async def test_sse_stream_carries_job_lifecycle(live_server: str) -> None:
    # SSE needs a real server: httpx's ASGITransport buffers whole responses,
    # so an open-ended event stream can never be read through it.
    async with httpx.AsyncClient(
        base_url=live_server, headers={"Authorization": f"Bearer {TEST_TOKEN}"}
    ) as client:
        session_id, payload_id = await _session_with_payload(client)

        events: list[str] = []

        async def read_events() -> None:
            async with client.stream("GET", f"/v1/sessions/{session_id}/events") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        events.append(line.removeprefix("event: "))
                    if line == "event: job.completed":
                        return

        reader = asyncio.create_task(read_events())
        await asyncio.sleep(0.2)  # stream open before the job runs
        submit = await client.post(
            f"/v1/sessions/{session_id}/jobs", json={"graph": linear_graph(payload_id)}
        )
        assert submit.status_code == 201
        await asyncio.wait_for(reader, timeout=15)

    assert "job.status" in events
    assert "node.completed" in events
    assert "job.output" in events
    assert events[-1] == "job.completed"


async def test_modules_endpoint_lists_manifests(fake_client: httpx.AsyncClient) -> None:
    response = await fake_client.get("/v1/modules")
    assert response.status_code == 200
    names = {m["name"] for m in response.json()}
    assert {"test.upper", "test.suffix", "test.concat"} <= names
    manifest = next(m for m in response.json() if m["name"] == "test.upper")
    assert manifest["inputs"] == [{"name": "text", "type": TEXT}]
    assert manifest["isolation"] == "core"
