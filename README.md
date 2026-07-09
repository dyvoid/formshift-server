# Formshift Server

A standalone module execution engine: an HTTP process running a DAG of typed processing units, with
per-node caching, progressive results, and network-transparent execution. Runs one-shot, cached,
interactive pipelines — image processing today, any typed heterogeneous data tomorrow.

This repository is the server only. It has no dependency on, or knowledge of, any particular
client. [Formshift: Vector](../formshift-vector), a raster-to-vector tracing app, is the first
client and embeds this server as a subprocess; it lives in its own repository.

## Status

M0–M3 complete: HTTP API with token auth and sessions, parallel DAG executor with hash-chain
caching, job lifecycle with cancellation and SSE progress, core raster/color/tracing modules,
and isolated extension installation — extensions install into per-extension venvs
(`POST /v1/extensions`) so their dependency pins can conflict with core's without breaking
anything; background removal (rembg) is the first out-of-core extension. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for milestone sequencing and
[`docs/architecture/design.md`](docs/architecture/design.md) for the full design.

## Getting Started

```
# clone, install, run
uv sync
uv run formshift-server --port 0
# prints: formshift-server listening on http://127.0.0.1:<port>
#         token: <bearer token>
```

All endpoints except `GET /health` require `Authorization: Bearer <token>`. Quick tour with curl:

```
BASE=http://127.0.0.1:<port>; AUTH="Authorization: Bearer <token>"
curl -X POST -H "$AUTH" $BASE/v1/sessions                               # -> {"id": SID}
curl -X POST -H "$AUTH" --data-binary @logo.png \
     "$BASE/v1/sessions/$SID/payloads?type=raster/png"                  # -> {"id": PID}
curl -X POST -H "$AUTH" -H "Content-Type: application/json" -d '{
  "graph": {
    "nodes":    [{"id": "trace", "module": "potrace.trace", "params": {"blacklevel": 0.5}}],
    "bindings": [{"payload": "'$PID'", "node": "trace", "port": "image"}],
    "outputs":  [{"node": "trace", "port": "svg"}]
  }}' $BASE/v1/sessions/$SID/jobs                                       # -> {"id": JID}
curl -H "$AUTH" $BASE/v1/sessions/$SID/jobs/$JID                        # -> outputs[].payload
curl -H "$AUTH" $BASE/v1/sessions/$SID/payloads/<payload> -o out.svg
```

Run the test suite with `uv run pytest`; lint and type-check with `uv run ruff check .` and
`uv run mypy`. Two end-to-end tests download real packages from PyPI (extension isolation and
the rembg extension); they skip unless `FORMSHIFT_TEST_NETWORK=1` is set.

### Dev environment

- Python is managed by [uv](https://docs.astral.sh/uv/) (interpreter version pinned in
  `pyproject.toml`).
- The potrace module needs a `potrace` binary on `PATH`, or in the gitignored `tools/` directory
  (dev convention: `tools/potrace-1.16.win64/potrace.exe`, from the official
  [potrace 1.16 Windows release](https://potrace.sourceforge.net/download/1.16/potrace-1.16.win64.zip)).
  potrace is GPL-2.0 and is always invoked as a subprocess — never a linked binding; see the
  Constraints section of [docs/architecture/overview.md](docs/architecture/overview.md).

## Project Structure

```
src/formshift_server/   Server source (Python package, src layout)
extensions/              First-party extension sources (installed via /v1/extensions)
docs/                    Architecture, design, decisions, and guides
AGENTS.md                Context and instructions for AI agents
PICKUP.md                Session handoff — where the last session left off
```

## Documentation

- [Architecture Overview](docs/architecture/overview.md)
- [Design](docs/architecture/design.md)
- [Architecture Decisions](docs/adr/)
- [Git Strategy](docs/git-strategy.md)
- [Roadmap](docs/ROADMAP.md)
