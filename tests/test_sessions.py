"""Session and payload contract (ADR 0004)."""

import httpx
import pytest

pytestmark = pytest.mark.anyio


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/v1/sessions")
    assert response.status_code == 201
    session_id: str = response.json()["id"]
    return session_id


async def test_create_and_delete_session(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client)
    response = await client.delete(f"/v1/sessions/{session_id}")
    assert response.status_code == 204
    response = await client.delete(f"/v1/sessions/{session_id}")
    assert response.status_code == 404


async def test_payload_roundtrip(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client)
    data = b"\x89PNG fake bytes"

    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads",
        params={"type": "raster/png"},
        content=data,
    )
    assert upload.status_code == 201
    body = upload.json()
    assert body["type"] == "raster/png"

    download = await client.get(f"/v1/sessions/{session_id}/payloads/{body['id']}")
    assert download.status_code == 200
    assert download.content == data
    assert download.headers["X-Formshift-Type"] == "raster/png"


async def test_upload_requires_type(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client)
    response = await client.post(f"/v1/sessions/{session_id}/payloads", content=b"data")
    assert response.status_code == 422


async def test_empty_payload_rejected(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client)
    response = await client.post(
        f"/v1/sessions/{session_id}/payloads", params={"type": "raster/png"}, content=b""
    )
    assert response.status_code == 400


async def test_unknown_session_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/sessions/nope/payloads", params={"type": "raster/png"}, content=b"data"
    )
    assert response.status_code == 404


async def test_deleted_session_drops_payloads(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client)
    upload = await client.post(
        f"/v1/sessions/{session_id}/payloads", params={"type": "raster/png"}, content=b"data"
    )
    payload_id = upload.json()["id"]
    await client.delete(f"/v1/sessions/{session_id}")
    response = await client.get(f"/v1/sessions/{session_id}/payloads/{payload_id}")
    assert response.status_code == 404
