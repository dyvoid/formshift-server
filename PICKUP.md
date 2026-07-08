# PICKUP

Where the last session left off. Update this when you stop, so the next session starts with context
instead of archaeology.

## Current focus

Starting M0 ("Trace" server slice) — see [docs/ROADMAP.md](docs/ROADMAP.md) and the Milestones
section of [docs/architecture/design.md](docs/architecture/design.md).

## State

- Docs are standalone: full design in `docs/architecture/design.md`; the original proposal was
  removed from the working tree and lives in the first commit's history.
- No implementation yet: no `pyproject.toml`, no package contents, no tests, no CI workflow.
- Working autonomously per user authorization (2026-07-08); commits stay local, no pushing.

## Next

M0 skeleton on a `task/` branch: `pyproject.toml` (uv, Python 3.12 pin, fastapi/uvicorn deps,
ruff+mypy+pytest config), `src/formshift_server` package skeleton, smoke test, merge to main. Then
M0 proper: HTTP API with token auth + sessions, linear DAG executor, hash-chain cache, potrace
module — ADRs alongside each frozen contract piece.

## Open questions

- CI workflow (GitHub Actions) not yet configured; add once there's a test suite worth gating on.
- potrace Windows binary to be downloaded into gitignored `tools/` (user-authorized).

---
*Last updated: 2026-07-08*
