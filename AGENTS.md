# AGENTS.md

This file is the primary context source for AI agents working in this repository. Read it before
doing anything else, and follow the instructions here. For deeper context on a specific topic,
follow the links in the index at the bottom.

This is the one place that governs how AI agents behave in this repo. The linked docs carry context
and decisions; they deliberately avoid AI-specific directives so there's no second source of truth.

**Before doing any git work** (commits, branches, merges) **read [Git Strategy](docs/git-strategy.md)
in full.** Do not commit, branch, or merge based on assumption or partial recollection of the rules.

---

## Project Overview

Formshift Server is a standalone module execution engine: an HTTP process running a DAG of typed
processing units, with per-node caching, progressive results, and network-transparent execution.
It executes one-shot, cached, interactive pipelines — nothing else (no streaming/timeline media, no
realtime processing, no cross-module GPU residency, no job scheduler).

**This repository is the server only.** It has no knowledge of any particular client. Formshift:
Vector (a raster-to-vector tracing app) is the first client and lives in a separate repository; it
embeds this server as a subprocess. Do not add Vector-specific concepts (layers, tracing, potrace
UI, etc.) here — those belong in the module manifests and in the client repo, not the engine.

The full design — rationale, competitive analysis, contracts, build strategy, milestones, open
risks — lives in [Design](docs/architecture/design.md). Treat it as the source of truth for this
repo's scope and sequencing. (The original two-part proposal that also covered Vector is preserved
in git history as `formshift-proposal.md` in the first commit.)

---

## Architecture

Python HTTP service exposing a discrete request/response API plus one multiplexed SSE channel for
job progress. Modules are out-of-process, black-box units identified purely by typed I/O ports (an
open string namespace like `raster/png`, `vector/svg`); the engine only enforces that connected
ports match, never what happens inside a module. See [Architecture Overview](docs/architecture/overview.md)
for the full picture, and [the ADR log](docs/adr/) for the reasoning behind specific decisions.

---

## AI Instructions

### You can do these freely
- Write, edit, and refactor code that follows the patterns already in the codebase
- Create new files consistent with existing conventions
- Update documentation to match code changes
- Add tests for new or existing functionality

### These need human review before they land
- `.gitignore` and `.gitattributes`
- Authentication, authorization, or anything touching secrets (this server's token auth is
  security-load-bearing even on localhost — see the Security section of [Design](docs/architecture/design.md))
- Dependency changes (lockfiles, package manifests)
- Refactors that cut across multiple modules
- CI/CD configuration

### Do not do these
- Commit directly to `main`, except the two cases in [Git Strategy](docs/git-strategy.md#branch-protection)
  (non-functional changes, or explicit user sign-off for this change)
- Delete or rename files without being asked
- Change architecture without recording an ADR in `docs/adr/`
- Add third-party dependencies without explicit instruction
- Freeze or "finalize" any part of the HTTP protocol, module manifest format, type-string registry,
  or session/auth semantics without an ADR — these are the project's forward-only contracts (see
  the Build Strategy section of [Design](docs/architecture/design.md)); breaking one after it
  ships is the one kind of regression this project treats as unrecoverable
- Widen scope past the current milestone's exit condition (see `docs/ROADMAP.md`). Filling in a
  stubbed implementation behind an already-frozen contract is fine; adding new contract surface
  ahead of the milestone that needs it is not

---

## Conventions

### Branching
Short-lived branches only: `task/`, `fix/`, `experiment/`. Details in [Git Strategy](docs/git-strategy.md).

### Commits
One commit per task or prompt session. [Conventional Commits](https://www.conventionalcommits.org).
Put AI context in the body, not the subject:

```
feat(scope): short imperative summary

ai-assisted: <model>
```

### Python specifics
- **Dependency manager:** `uv`. Python version pinned in `pyproject.toml`. Do not switch either
  without being asked.
- Commit the lockfile (`uv.lock`); never commit the virtualenv.
- **Lint/format/type-check:** `ruff` + `mypy`. Match the existing toolchain, don't introduce a
  competing one (e.g. `black`, `flake8`).
- **Type hints on every function**, public and private — not just public signatures.
- **Package layout: `src/formshift_server/`** (PyPA `src/` layout), so tests exercise the installed
  package, not the working copy.
- Don't scaffold a `tests/` directory pre-emptively; add it when the first test is written, and use
  `pytest` as the runner.
- **Isolation is structural, not incidental.** The core extension (classical CV: PIL, numpy, scipy,
  scikit-image) runs in the main process/venv. Everything else is designed to run in its own
  isolated venv/process on demand (see the Extensions section of [Design](docs/architecture/design.md)). Don't
  add a heavy or ML-adjacent dependency to the core package's own dependency set — it belongs in an
  extension's own manifest, even before extension isolation is actually implemented (pre-M3, an
  unimplemented isolation value is a deliberate not-implemented error, not a silent shared install).

---

## Document Index

| Document | What it covers |
|---|---|
| [Architecture Overview](docs/architecture/overview.md) | System structure, key components, data flow |
| [Design](docs/architecture/design.md) | Full server design: rationale, contracts, build strategy, milestones, open risks |
| [ADR Log](docs/adr/) | Architecture decisions and their rationale |
| [Roadmap](docs/ROADMAP.md) | Feature candidates, planned work, and status |
| [Git Strategy](docs/git-strategy.md) | Branching, merging, commit rules |
| [PICKUP](PICKUP.md) | Where the last session left off — active work only, not the backlog |
