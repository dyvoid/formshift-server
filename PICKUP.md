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
- A post-session review pass fixed two manifest-validation edge cases (duplicate module names
  half-registering; non-table modules entries returning 500 instead of 422).
- 121 tests pass without network; 2 more are gated behind `FORMSHIFT_TEST_NETWORK=1` (real PyPI
  downloads). ruff + mypy strict clean (src, tests, scripts). ADRs 0002–0015.

## Session notes (2026-07-18, local)

- Added `image.invert` core module (`raster/png` → `raster/png`, no params) — per-channel
  invert via `ImageOps.invert`, flattens alpha → RGB first like the other tonal modules.
  New module behind an already-frozen contract; no ADR needed. Registered in
  `default_registry()` between `image.threshold` and `image.downsample`. 4 new tests in
  `tests/test_raster_modules.py`; full suite green (121 pass, 2 network-gated skip),
  ruff + mypy clean. Committed directly to `main` with user sign-off per git-strategy.md.
- PICKUP.md staleness corrected: the "Next" section previously listed CI as drafted on
  `task/ci-quality-gate` awaiting review, and tags `m2`/`m3`/`m4` as needing recreation.
  Both were stale — CI is merged on `main` (commit `aa1ad91`, `.github/workflows/ci.yml`,
  ubuntu + windows matrix, tests + ruff + mypy + build, action SHAs pinned, potrace
  download checksummed), and all four milestone tags exist locally. The branch
  `task/ci-quality-gate` no longer exists. Updated "Next" and "Open questions" to match.
- Architecture comparison vs ComfyUI's backend (DAG + per-node cache + progressive
  streaming) done in conversation. Conclusion recorded for future sessions: on the shared
  axis ComfyUI's backend is more mature (cache strategies, real queue, intra-node progress,
  real-workload hardening); on isolation, heterogeneous I/O, security, and contract
  discipline this engine is structurally ahead. Recommendation: do **not** add
  ComfyUI-parity items to the roadmap speculatively — the missing ones are either already
  tracked (eviction on M5, scheduler as a known open risk) or solve workloads this engine
  doesn't have (intra-node progress, hierarchical subcaches). The one actionable addition
  is a non-Vector reference extension, now logged as a Candidate in
  [docs/ROADMAP.md](docs/ROADMAP.md) — the cheapest way to falsify the agnostic-engine
  claim without waiting for a real second consumer.

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
  them from a normal checkout: `m2` = 9145666, `m3` = 41388ac, `m4` = f6cce1c.
- Live CLI smoke re-verified after the worker change: server booted with `--extensions-dir`, an
  extension installed over HTTP with curl and its module ran through the persistent worker.
- Known sharp edge, deliberate for now: a corrupted extension directory (unparseable copied
  manifest next to an `installed.json`) fails server startup loudly rather than being skipped.
  Revisit if it ever bites.

## Next

M5 is gated on a non-Vector consumer; don't start it without one. Worthwhile non-gated work:

- Extension uninstall/upgrade endpoints once something needs them (ADR 0013).
- Raw-buffer interchange for co-located modules (`raster/rgba8`) — roadmap candidate; profile a
  real client workload first (M1 baseline showed ~129 ms/node PNG codec cost at 3000×2250).

## Open questions

- Cache memory budget / eviction policy still unresolved (flagged for M5).
- LAN token distribution / transport security still undesigned (flagged in design doc).
- Milestone tags `m0`–`m4` exist locally; remote push state unverified from this machine (SSH key
  not available for `git ls-remote`). If any are missing on `origin`, push them from a checkout
  that has push access.

---
*Last updated: 2026-07-18 (PICKUP staleness corrected same day)*
