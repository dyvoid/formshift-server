# Formshift Server

[![CI](https://github.com/dyvoid/formshift-server/actions/workflows/ci.yml/badge.svg)](https://github.com/dyvoid/formshift-server/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)

A standalone module execution engine: an HTTP process running a DAG of typed processing units, with
per-node caching, progressive results, and network-transparent execution. Runs one-shot, cached,
interactive pipelines — image processing today, any typed heterogeneous data tomorrow.

## What this actually is

Say you want to turn a PNG logo into an SVG trace, then posterize it into a few flat colors, then
merge those colors back into one file. Each of those steps is a separate operation with its own
knobs (threshold, color count, ...), and a client (a desktop app, a CLI, a script) needs to chain
them together, re-run only the steps that changed when a knob moves, and show partial results while
the rest of the pipeline is still running.

Formshift Server is the engine that does that chaining, caching, and streaming, over plain HTTP, so
no client has to reimplement it. You describe the pipeline as a graph of nodes ("trace this payload
with `potrace.trace` using these params, then feed the result into `image.posterize`") and POST it
as a job. The server walks the graph, dispatches each node to the module that implements it, caches
each node's output so an unrelated edit downstream doesn't force a full re-run, and streams results
back as they complete.

It has no UI and no opinion about what created the graph.
[Formshift: Vector](https://github.com/dyvoid/formshift-vector), a raster-to-vector tracing app, is
the first client and embeds this server as a subprocess (its own repository); this repo is the
server only, speaks nothing but HTTP, and can be driven directly with curl (see
[Getting Started](#getting-started) below).

## How it works

```
Client (HTTP)
   │  upload payload → session ID
   │  POST job (graph: nodes + typed edges)
   ▼
┌─────────────────────────────────────────────┐
│ Formshift Server                             │
│                                               │
│  Session/Auth ── HTTP API ── SSE (progress)  │
│                     │                        │
│              DAG Executor                    │
│           (topological walk)                 │
│                     │                        │
│         ┌───────────┼───────────┐            │
│         ▼           ▼           ▼            │
│      Module A    Module B    Module C        │
│    (core, in-  (local, out-  (remote,        │
│     process)    of-process)   bytes-over-     │
│                                wire)          │
│                     │                        │
│               Hash-chain Cache               │
│         (per-node, keyed on params +         │
│          upstream input hashes)              │
└─────────────────────────────────────────────┘
```

A handful of concepts cover the whole surface:

- **Sessions** — a workspace scoped to one client connection. You create a session, then upload
  payloads and submit jobs against it.
- **Payloads** — binary data (a PNG, an SVG, ...) uploaded once to a session and referenced by ID
  from then on. Payloads never travel as base64-in-JSON or filesystem paths — only as uploaded
  bytes, referenced by ID — because that's the one representation that still works once client and
  server are different machines.
- **Jobs & graphs** — a job is a graph: node instances (each naming a module and its params) plus
  typed edges binding payloads and node outputs to node inputs. Ports are strictly type-checked at
  connection time (e.g. a `vector/svg` output can't be wired into a `raster/png` input).
- **Modules** — the black-box processing units themselves (`potrace.trace`, `image.posterize`,
  `svg.merge`, ...), identified purely by their typed I/O ports. A module can run in-process
  (core), as a local out-of-process worker, or remotely — the graph doesn't care which.
- **DAG executor** — walks the graph topologically and runs independent branches concurrently. A
  single-node graph is just the degenerate case of the general executor.
- **Hash-chain cache** — each node's cache key is its own params plus the hash of its upstream
  inputs. Reordering or editing one node in the graph reruns only what's actually downstream of the
  change, not the whole pipeline.
- **Progressive results (SSE)** — one multiplexed Server-Sent-Events stream per client carries job
  progress and completed outputs as they materialize, either as soon as each is ready (disjoint
  outputs) or held to a declared order when outputs are meant to overlap (pinned-order groups).
- **Extensions & isolation** — modules ship in installable extensions. Core modules (PIL, numpy,
  scikit-image) run in the server's own environment; everything else installs into its own venv via
  `POST /v1/extensions` and runs as a persistent worker process, so an extension's dependency pins
  can conflict with core's without breaking anything.

See [Architecture Overview](docs/architecture/overview.md) for the fuller version of this and
[Design](docs/architecture/design.md) for the authoritative source (contracts, caching, security,
isolation model).

## Status

M0–M4 complete: HTTP API with token auth and sessions, parallel DAG executor with hash-chain
caching, job lifecycle with cancellation and SSE progress, core raster/color/tracing modules,
isolated extension installation — extensions install into per-extension venvs
(`POST /v1/extensions`) so their dependency pins can conflict with core's without breaking
anything; background removal (rembg) is the first out-of-core extension — and both progressive
rendering paths (completion-order streaming, pinned-order output groups for overlapping
results). See
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

All endpoints except `GET /health` require `Authorization: Bearer <token>`. Quick tour with curl —
create a session, upload a PNG, trace it to an SVG, and download the result:

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

The single-node graph above is the minimal case; multi-node graphs chain `bindings` from one node's
output port into another node's input port instead of from a payload, and `outputs` can list more
than one node/port pair to fetch several results from one job.

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
