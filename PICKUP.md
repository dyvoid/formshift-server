# PICKUP

Where the last session left off. Update this when you stop, so the next session starts with context
instead of archaeology.

## Current focus

Project scaffolding: AGENTS.md, docs, and repo conventions for the server-only repo. No engine code
written yet.

## State

- `formshift-proposal.md` (the full design doc, Parts 1 and 2) is in the repo root.
- AI project boilerplate generated: AGENTS.md, README.md, docs/ROADMAP.md,
  docs/architecture/overview.md, docs/adr/0001, docs/git-strategy.md, .gitignore, .gitattributes.
- No `pyproject.toml`, no `src/formshift_server` package contents, no CI workflow yet.
- Nothing committed to git yet (repo has an `origin` remote at `github.com:dyvoid/formshift-server`
  but no commits).

## Next

Start M0 ("Trace" server slice, see `docs/ROADMAP.md`): scaffold `pyproject.toml` (uv, Python
version pin, ruff+mypy config), the `src/formshift_server` package skeleton, and the frozen v1
contract surface (HTTP API with token auth + sessions, linear DAG executor, hash-chain cache,
potrace module in the core environment). Write an ADR for each contract piece before or as it's
frozen (see ADR 0001's `Proposed` status note).

## Open questions

- CI workflow provider/config not yet chosen (GitHub Actions is the obvious default given the
  `origin` remote, but unconfirmed with the user).
- Python version to pin has not been decided.

---
*Last updated: 2026-07-08*
