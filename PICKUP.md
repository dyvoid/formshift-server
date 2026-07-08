# PICKUP

Where the last session left off. Update this when you stop, so the next session starts with context
instead of archaeology.

## Current focus

M2 server slice complete and committed; next is M3 ("Extensions" server slice) — see
[docs/ROADMAP.md](docs/ROADMAP.md) and the Milestones section of
[docs/architecture/design.md](docs/architecture/design.md).

## State

- **M0 done, tagged `m0`** (exit verified over live HTTP with curl).
- **M1 done** (2026-07-08): core raster modules, reorder-invalidation verified at the API level,
  and the [M1 performance baseline](docs/performance-baseline.md) recorded on target hardware.
- **M2 done** (2026-07-08):
  - Multi-input merge module `svg.merge` with order-aware cache keys; ADR 0009.
  - Parallel executor: independent branches run concurrently on a thread pool; ADR 0010.
  - Color separation modules: `image.posterize`, `image.colormask`, `svg.colorize`; ADR 0011.
  - Progressive/disjoint streaming exercised end to end by a 16-color trace test.
  - Parallel speedup benchmark recorded in [docs/performance-parallel.md](docs/performance-parallel.md):
    2.45× on 8 cores for 1600×1600 16-color separation.
- 74 tests; ruff + mypy strict clean (src, tests, and scripts). ADRs 0002–0011.

## Next

M3 server-slice items (design doc, Milestones):
1. **Isolated-venv extension installation** — replace the current `NotImplementedError` stubs with
   real venv creation, dependency installation, and subprocess module loading.
2. **First out-of-core extension** — background removal (`rembg`-class) as the proof workload.
3. **Exit**: the extension installs into isolation on a machine where its dependency pins would
   conflict with core, and works.

## Open questions

- CI (GitHub Actions) still unconfigured; quality gate runs locally. Add when pushing to GitHub
  resumes (push policy is currently local-only per user instruction).
- M3 extension isolation design: separate venv per extension vs. shared extension venv; how to
  expose module manifests without importing extension code into core; dependency pin policy.

---
*Last updated: 2026-07-08*
