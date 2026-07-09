# PICKUP

Where the last session left off. Update this when you stop, so the next session starts with context
instead of archaeology.

## Current focus

M3 server slice complete and committed; next is M4 ("Print" server slice: pinned-order progressive
path for overlapping outputs) — see [docs/ROADMAP.md](docs/ROADMAP.md) and the Milestones section
of [docs/architecture/design.md](docs/architecture/design.md).

## State

- **M0 done, tagged `m0` locally** (exit verified over live HTTP with curl). Note: the `m0` tag was
  never pushed to GitHub — push it from the machine that has it, or accept its loss.
- **M1 done** (2026-07-08): core raster modules, reorder-invalidation verified at the API level,
  and the [M1 performance baseline](docs/performance-baseline.md) recorded on target hardware.
- **M2 done** (2026-07-08): `svg.merge` + color separation modules, parallel executor
  ([2.45× on 8 cores](docs/performance-parallel.md)), 16-color progressive e2e test. ADRs 0009–0011.
- **M3 done** (2026-07-09):
  - Extensions install into per-extension venvs; modules run out-of-process via a stdlib stdio
    runner behind the same `Module` protocol; ADR 0012.
  - `GET/POST /v1/extensions` (opt-in via `--extensions-dir`, disabled by default); ADR 0013.
  - Registry now honors isolation by construction (`register` vs `register_isolated`); the old
    NotImplementedError stub is gone, unknown isolation values still explicitly rejected.
  - First out-of-core extension: `extensions/background-removal` (rembg 2.0.76, `image.removebg`).
  - **Exit condition verified 2026-07-09**: `tests/test_extension_conflict_e2e.py` installs an
    extension pinning `pillow==10.4.0` against core's 12.x over the real HTTP API and runs it —
    conflicting pins, isolated venv, correct output. Verified in-session on Linux/py3.12.
- 100 tests pass without network; 2 more are gated behind `FORMSHIFT_TEST_NETWORK=1` (real PyPI
  downloads). ruff + mypy strict clean (src, tests, scripts). ADRs 0002–0013.

## Session notes (2026-07-09, remote sandbox)

- The conflict-pin e2e test **passed** here end to end (PyPI is reachable in the sandbox).
- The rembg e2e test (`tests/test_removebg_e2e.py`) ran to the point of model-weight download,
  which this sandbox's egress policy blocks (GitHub releases + Hugging Face → 403). Verified
  instead: `rembg[cpu]==2.0.76` + onnxruntime 1.27 + numpy 2.4.6 pip-install into the extension
  venv and import cleanly there, while core has no numpy at all. **Run
  `FORMSHIFT_TEST_NETWORK=1 uv run pytest tests/test_removebg_e2e.py` once on an open-network
  machine to see the full cut-out path green.** Model weights land in `U2NET_HOME`
  (default `~/.u2net`); the test redirects them to a tmp dir.

## Next

M4 server-slice items (design doc, Milestones):
1. **Pinned-order progressive path** — the second progressive-rendering code path: output groups
   that deliberately overlap (print separations with underbase) must stream in pinned order, not
   completion order.
2. **Exit**: overlapping output groups render in pinned order, verified by test.

M3 follow-ups worth picking up opportunistically (none block M4):
- Persistent per-extension worker process (amortize model load; ADR 0012 records the upgrade path
  behind the same adapter).
- Extension uninstall/upgrade endpoints once something needs them (ADR 0013).

## Open questions

- CI (GitHub Actions) still unconfigured; quality gate runs locally. The repo now lives on GitHub
  (`dyvoid/formshift-server`, `main` pushed 2026-07-09), so CI is actionable whenever the user
  wants it — needs human review per AGENTS.md.
- Cache memory budget / eviction policy still unresolved (flagged for M5).
- LAN token distribution / transport security still undesigned (flagged in design doc).

---
*Last updated: 2026-07-09*
