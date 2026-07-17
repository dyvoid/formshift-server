"""Auth and Host/Origin guard behavior (ADR 0003)."""

import httpx
import pytest

from formshift_server.app import create_app
from formshift_server.config import ServerConfig

from .conftest import TEST_TOKEN

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


async def test_cors_headers_are_absent_by_default(anon_client: httpx.AsyncClient) -> None:
    response = await anon_client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


async def test_configured_cors_origin_receives_response_header() -> None:
    config = ServerConfig(
        token=TEST_TOKEN,
        token_explicit=True,
        cors_origins=("http://localhost:5173",),
    )
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


async def test_configured_cors_origin_can_preflight_authenticated_request() -> None:
    config = ServerConfig(
        token=TEST_TOKEN,
        token_explicit=True,
        cors_origins=("http://localhost:5173",),
    )
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.options(
            "/v1/sessions",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "authorization" in response.headers["Access-Control-Allow-Headers"].lower()
