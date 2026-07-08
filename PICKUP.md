# PICKUP

Where the last session left off. Update this when you stop, so the next session starts with context
instead of archaeology.

## Current focus

M1 server slice complete; next is M2 ("Color" server slice) — see
[docs/ROADMAP.md](docs/ROADMAP.md) and the Milestones section of
[docs/architecture/design.md](docs/architecture/design.md).

## State

- **M0 done, tagged `m0`** (exit verified over live HTTP with curl).
- **M1 server slice done** (2026-07-08): core raster modules (crop, rotate, levels, threshold,
  draft-aware downsample per ADR 0008), reorder-invalidation verified at the API level, and the
  [performance baseline](docs/performance-baseline.md) recorded on target hardware.
- Key baseline finding: ~129 ms per added node at 3000×2250, dominated by PNG codec cost at each
  edge — empirically confirms the design doc's transport-tier warning; a raw-buffer interchange
  type is a roadmap Candidate, deliberately deferred until a real client workload is profiled.
- 66 tests; ruff + mypy strict clean. ADRs 0002–0008.

## Next

M2 server-slice items (design doc, Milestones):
1. **Multi-input merge module** — the executor and cache already handle multi-input nodes
   (order-aware keys, tested); what's missing is a real core module (e.g. mask combine or SVG
   layer merge) to drive it over HTTP.
2. **Parallel execution of independent nodes** — the executor walks strictly sequentially today;
   independent branches (per-color traces) should run concurrently. Benchmark the speedup on this
   machine as the M2 exit requires.
3. **Progressive streaming, disjoint path** — job.output events already fire per output as nodes
   complete; what M2 adds is a workload that actually exercises multiple progressive outputs
   (16-color trace) end to end.
4. Posterize/color-separation core modules to make the 16-color trace real (posterize → N masks →
   N potrace runs → merged SVG).

## Open questions

- CI (GitHub Actions) still unconfigured; quality gate runs locally. Add when pushing to GitHub
  resumes (push policy is currently local-only per user instruction).
- Parallel executor design: thread pool inside execute_graph vs. per-node futures — decide when
  starting M2 item 2; cache and event log are already thread-safe.

---
*Last updated: 2026-07-08*
