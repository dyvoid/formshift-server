# Formshift Server

A standalone module execution engine: an HTTP process running a DAG of typed processing units, with
per-node caching, progressive results, and network-transparent execution. Runs one-shot, cached,
interactive pipelines — image processing today, any typed heterogeneous data tomorrow.

This repository is the server only. It has no dependency on, or knowledge of, any particular
client. [Formshift: Vector](../formshift-vector), a raster-to-vector tracing app, is the first
client and embeds this server as a subprocess; it lives in its own repository.

## Status

Pre-M0. No implementation yet — this repo currently holds the design docs and project
scaffolding. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for milestone sequencing and
[`docs/architecture/design.md`](docs/architecture/design.md) for the full design.

## Getting Started

```
# clone, install, run
uv sync
uv run formshift-server --port 0
```

(Entry point not implemented yet — see `docs/ROADMAP.md` for M0 scope.)

## Project Structure

```
src/formshift_server/   Server source (Python package, src layout)
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
