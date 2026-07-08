from collections.abc import AsyncIterator

import httpx
import pytest

from formshift_server.app import create_app
from formshift_server.config import ServerConfig

TEST_TOKEN = "test-token-for-suite"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def config() -> ServerConfig:
    return ServerConfig(token=TEST_TOKEN, token_explicit=True)


@pytest.fixture
async def client(config: ServerConfig) -> AsyncIterator[httpx.AsyncClient]:
    """Authenticated client against an in-process app (no real socket)."""
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as client:
        yield client


@pytest.fixture
async def anon_client(config: ServerConfig) -> AsyncIterator[httpx.AsyncClient]:
    """Client with no Authorization header."""
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        yield client
