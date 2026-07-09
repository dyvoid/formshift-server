# PICKUP

Where the last session left off. Update this when you stop, so the next session starts with context
instead of archaeology.

## Current focus

M3 and M4 server slices complete and committed; next is M5 ("Open house"), which is **gated on a
non-Vector consumer existing** — do not start it speculatively. Until that gate opens, the useful
work is the follow-ups list below and whatever the Vector client surfaces — see
[docs/ROADMAP.md](docs/ROADMAP.md) and the Milestones section of
[docs/architecture/design.md](docs/architecture/design.md).

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
- **M4 done** (2026-07-09):
  - Pinned-order output groups: `outputs[].group` + `groups[].order` (`completion` | `pinned`);
    the job layer holds pinned-group outputs so they emit in declared order; ADR 0014.
  - **Exit condition verified 2026-07-09**: `tests/test_pinned_order.py` builds a fan-out where
    the first-declared output completes last and asserts it still emits first (plus: groups don't
    block each other, completion groups still stream, invalid group specs are 422s).
- **Persistent extension workers** (2026-07-09, post-M4 follow-up): one long-lived worker process
  per extension replaces process-per-invocation; imports/model sessions amortize across runs
  (removebg now caches its ONNX session), crash/hang → ModuleError + respawn on next request,
  requests serialized per worker; ADR 0015. Verified: reuse, exception-survival, hard-crash
  respawn, concurrency tests, plus the gated conflict e2e re-run green over the worker path.
- 108 tests pass without network; 2 more are gated behind `FORMSHIFT_TEST_NETWORK=1` (real PyPI
  downloads). ruff + mypy strict clean (src, tests, scripts). ADRs 0002–0015.

## Session notes (2026-07-09, remote sandbox)

- The conflict-pin e2e test **passed** here end to end (PyPI is reachable in the sandbox).
- The rembg e2e test (`tests/test_removebg_e2e.py`) ran to the point of model-weight download,
  which this sandbox's egress policy blocks (GitHub releases + Hugging Face → 403). Verified
  instead: `rembg[cpu]==2.0.76` + onnxruntime 1.27 + numpy 2.4.6 pip-install into the extension
  venv and import cleanly there, while core has no numpy at all. **Run
  `FORMSHIFT_TEST_NETWORK=1 uv run pytest tests/test_removebg_e2e.py` once on an open-network
  machine to see the full cut-out path green.** Model weights land in `U2NET_HOME`
  (default `~/.u2net`); the test redirects them to a tmp dir.
- Milestone tags: `m1` pushed; pushes of `m2`/`m3`/`m4` got persistent 403s from the session's
  git proxy (branch pushes work fine). Tags exist locally in the sandbox clone — recreate/push
  them from a normal checkout: `m2` = 9145666, `m3` = 41388ac, `m4` = the M4 merge commit.

## Next

M5 is gated on a non-Vector consumer; don't start it without one. Worthwhile non-gated work:

- Extension uninstall/upgrade endpoints once something needs them (ADR 0013).
- Raw-buffer interchange for co-located modules (`raster/rgba8`) — roadmap candidate; profile a
  real client workload first (M1 baseline showed ~129 ms/node PNG codec cost at 3000×2250).
- CI (GitHub Actions): repo is on GitHub now and the quality gate is scriptable
  (`uv run pytest`, `ruff check .`, `mypy`, `mypy tests scripts`) — needs human review per
  AGENTS.md before landing.

## Open questions

- CI (GitHub Actions) still unconfigured; quality gate runs locally. The repo now lives on GitHub
  (`dyvoid/formshift-server`, `main` pushed 2026-07-09), so CI is actionable whenever the user
  wants it — needs human review per AGENTS.md.
- Cache memory budget / eviction policy still unresolved (flagged for M5).
- LAN token distribution / transport security still undesigned (flagged in design doc).

---
*Last updated: 2026-07-09*
