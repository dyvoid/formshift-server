"""FastAPI application factory.

Contract surface per ADRs 0002-0004: /health outside the version prefix,
everything else under /v1, bearer-token auth and Host/Origin validation
enforced as middleware so no endpoint can forget them.
"""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from . import __version__
from .cache import ResultCache
from .config import ServerConfig
from .core import (
    ColorMaskModule,
    CropModule,
    DownsampleModule,
    LevelsModule,
    PosterizeModule,
    PotraceModule,
    RotateModule,
    SvgColorizeModule,
    SvgMergeModule,
    ThresholdModule,
)
from .extensions import ExtensionConflictError, ExtensionError, ExtensionManager
from .graph import GraphValidationError, parse_graph, validate_graph
from .jobs import JobManager
from .modules import ModuleRegistry
from .sessions import Session, SessionStore

_AUTH_EXEMPT_PATHS = frozenset({"/health"})

_SSE_POLL_SECONDS = 0.05
_SSE_KEEPALIVE_SECONDS = 15.0


def default_registry() -> ModuleRegistry:
    registry = ModuleRegistry()
    registry.register(PotraceModule())
    registry.register(CropModule())
    registry.register(RotateModule())
    registry.register(LevelsModule())
    registry.register(ThresholdModule())
    registry.register(DownsampleModule())
    registry.register(PosterizeModule())
    registry.register(ColorMaskModule())
    registry.register(SvgColorizeModule())
    registry.register(SvgMergeModule())
    return registry


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


def create_app(config: ServerConfig, registry: ModuleRegistry | None = None) -> FastAPI:
    app = FastAPI(title="Formshift Server", version=__version__, openapi_url=None, docs_url=None)
    store = SessionStore()
    registry = registry if registry is not None else default_registry()
    cache = ResultCache()
    managers: dict[str, JobManager] = {}
    extensions: ExtensionManager | None = None
    if config.extensions_dir is not None:
        extensions = ExtensionManager(config.extensions_dir, registry)
        extensions.load_installed()

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

    def _manager_or_404(session_id: str) -> JobManager:
        manager = managers.get(session_id)
        if manager is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return manager

    @app.post("/v1/sessions", status_code=201)
    def create_session() -> dict[str, str]:
        session = store.create()
        managers[session.id] = JobManager(session, registry, cache, workers=config.workers)
        return {"id": session.id}

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str) -> None:
        if not store.delete(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        managers.pop(session_id, None)

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

    @app.get("/v1/modules")
    def list_modules() -> list[dict[str, Any]]:
        return [
            {
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "isolation": m.isolation,
                "inputs": [{"name": p.name, "type": p.type} for p in m.inputs],
                "outputs": [{"name": p.name, "type": p.type} for p in m.outputs],
            }
            for m in registry.manifests()
        ]

    @app.get("/v1/extensions")
    def list_extensions() -> dict[str, Any]:
        # "enabled" lets a client feature-detect without probing POST (ADR 0013).
        if extensions is None:
            return {"enabled": False, "extensions": []}
        return {
            "enabled": True,
            "extensions": [
                {
                    "name": e.manifest.name,
                    "version": e.manifest.version,
                    "description": e.manifest.description,
                    "isolation": e.manifest.isolation,
                    "modules": [spec.manifest.name for spec in e.manifest.modules],
                }
                for e in extensions.installed()
            ],
        }

    @app.post("/v1/extensions", status_code=201)
    async def install_extension(request: Request) -> dict[str, Any]:
        # Synchronous install: venv creation and dependency download run to
        # completion before responding (ADR 0013 records the trade-off).
        if extensions is None:
            raise HTTPException(
                status_code=503, detail="extension installation is disabled (no --extensions-dir)"
            )
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Body must be JSON") from exc
        path = body.get("path")
        if not isinstance(path, str) or not path:
            raise HTTPException(status_code=400, detail="'path' (extension source dir) required")
        try:
            installed = await asyncio.to_thread(extensions.install, Path(path))
        except ExtensionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ExtensionError, NotImplementedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "name": installed.manifest.name,
            "version": installed.manifest.version,
            "modules": [spec.manifest.name for spec in installed.manifest.modules],
        }

    @app.post("/v1/sessions/{session_id}/jobs", status_code=201)
    async def submit_job(session_id: str, request: Request) -> dict[str, Any]:
        session = _session_or_404(session_id)
        manager = _manager_or_404(session_id)
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Body must be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object")
        try:
            graph = parse_graph(body.get("graph") or {})
        except GraphValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors) from exc
        draft = bool(body.get("draft", False))
        errors = validate_graph(graph, registry, session)
        if errors:
            raise HTTPException(status_code=422, detail=errors)
        job = manager.submit(graph, draft)
        return {"id": job.id, "status": job.status.value}

    @app.get("/v1/sessions/{session_id}/jobs/{job_id}")
    def get_job(session_id: str, job_id: str) -> dict[str, Any]:
        manager = _manager_or_404(session_id)
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job.to_json()

    @app.delete("/v1/sessions/{session_id}/jobs/{job_id}", status_code=204)
    def cancel_job(session_id: str, job_id: str) -> None:
        manager = _manager_or_404(session_id)
        if not manager.cancel(job_id):
            raise HTTPException(status_code=404, detail="Job not found")

    @app.get("/v1/sessions/{session_id}/events")
    async def events(session_id: str) -> StreamingResponse:
        manager = _manager_or_404(session_id)

        async def stream() -> Any:
            cursor = 0
            idle = 0.0
            while True:
                fresh = manager.events.since(cursor)
                if fresh:
                    for event in fresh:
                        yield event.sse()
                    cursor = fresh[-1].index + 1
                    idle = 0.0
                else:
                    await asyncio.sleep(_SSE_POLL_SECONDS)
                    idle += _SSE_POLL_SECONDS
                    if idle >= _SSE_KEEPALIVE_SECONDS:
                        yield ": keepalive\n\n"
                        idle = 0.0

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Expose internals for tests and later components.
    app.state.store = store
    app.state.config = config
    app.state.registry = registry
    app.state.cache = cache
    app.state.managers = managers
    app.state.extensions = extensions

    return app
