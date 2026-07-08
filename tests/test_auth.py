"""Auth and Host/Origin guard behavior (ADR 0003)."""

import httpx
import pytest

pytestmark = pytest.mark.anyio


async def test_health_needs_no_auth(anon_client: httpx.AsyncClient) -> None:
    response = await anon_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_missing_token_is_401(anon_client: httpx.AsyncClient) -> None:
    response = await anon_client.post("/v1/sessions")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_wrong_token_is_401(anon_client: httpx.AsyncClient) -> None:
    response = await anon_client.post(
        "/v1/sessions", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401


async def test_non_bearer_scheme_is_401(anon_client: httpx.AsyncClient) -> None:
    response = await anon_client.post(
        "/v1/sessions", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )
    assert response.status_code == 401


async def test_correct_token_passes(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/sessions")
    assert response.status_code == 201


async def test_disallowed_host_is_403(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Host": "evil.example.com"})
    assert response.status_code == 403


async def test_localhost_host_with_port_passes(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Host": "localhost:7457"})
    assert response.status_code == 200


async def test_ipv6_loopback_host_passes(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Host": "[::1]:7457"})
    assert response.status_code == 200


async def test_disallowed_origin_is_403(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert response.status_code == 403


async def test_null_origin_is_403(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "null"})
    assert response.status_code == 403


async def test_localhost_origin_passes(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
