"""FastAPI application factory.

Contract surface per ADRs 0002-0004: /health outside the version prefix,
everything else under /v1, bearer-token auth and Host/Origin validation
enforced as middleware so no endpoint can forget them.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response

from . import __version__
from .config import ServerConfig
from .sessions import Session, SessionStore

_AUTH_EXEMPT_PATHS = frozenset({"/health"})


def _hostname_of(header_value: str) -> str:
    """Strip the port from a Host header or Origin host, keeping IPv6 brackets."""
    value = header_value.strip()
    if value.startswith("["):  # [::1]:8080 or [::1]
        return value.split("]", 1)[0] + "]"
    return value.rsplit(":", 1)[0] if ":" in value else value


def _origin_hostname(origin: str) -> str | None:
    """Hostname of an Origin header, or None if it isn't a plain http(s) origin."""
    for scheme in ("http://", "https://"):
        if origin.startswith(scheme):
            return _hostname_of(origin[len(scheme) :])
    return None


def create_app(config: ServerConfig) -> FastAPI:
    app = FastAPI(title="Formshift Server", version=__version__, openapi_url=None, docs_url=None)
    store = SessionStore()

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        # Host allowlist: blocks DNS rebinding (ADR 0003).
        host = request.headers.get("host", "")
        if _hostname_of(host) not in config.allowed_hosts:
            return Response(status_code=403, content="Host not allowed")

        # Origin allowlist, only when the header is present. "null" is rejected.
        origin = request.headers.get("origin")
        if origin is not None:
            origin_host = _origin_hostname(origin)
            if origin_host is None or origin_host not in config.allowed_hosts:
                return Response(status_code=403, content="Origin not allowed")

        if request.url.path not in _AUTH_EXEMPT_PATHS:
            auth = request.headers.get("authorization", "")
            scheme, _, credential = auth.partition(" ")
            if scheme.lower() != "bearer" or not secrets.compare_digest(
                credential.strip(), config.token
            ):
                return Response(
                    status_code=401,
                    content="Missing or invalid bearer token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    def _session_or_404(session_id: str) -> Session:
        session = store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    @app.post("/v1/sessions", status_code=201)
    def create_session() -> dict[str, str]:
        return {"id": store.create().id}

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str) -> None:
        if not store.delete(session_id):
            raise HTTPException(status_code=404, detail="Session not found")

    @app.post("/v1/sessions/{session_id}/payloads", status_code=201)
    async def upload_payload(
        session_id: str,
        request: Request,
        type: Annotated[str, Query(min_length=1, description="Type string, e.g. raster/png")],
    ) -> dict[str, str]:
        session = _session_or_404(session_id)
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="Empty payload body")
        payload = session.add_payload(type, data)
        return {"id": payload.id, "type": payload.type}

    @app.get("/v1/sessions/{session_id}/payloads/{payload_id}")
    def download_payload(session_id: str, payload_id: str) -> Response:
        session = _session_or_404(session_id)
        payload = session.payloads.get(payload_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Payload not found")
        return Response(
            content=payload.data,
            media_type="application/octet-stream",
            headers={"X-Formshift-Type": payload.type},
        )

    # Expose the store for later components (executor, jobs) and tests.
    app.state.store = store
    app.state.config = config

    return app
