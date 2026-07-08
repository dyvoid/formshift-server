# PICKUP

Where the last session left off. Update this when you stop, so the next session starts with context
instead of archaeology.

## Current focus

M1 ("Pipeline" server slice) — see [docs/ROADMAP.md](docs/ROADMAP.md) and the Milestones section of
[docs/architecture/design.md](docs/architecture/design.md).

## State

- **M0 complete and exit-verified** (2026-07-08): token-auth HTTP API, sessions/payloads, graph
  validation, topological executor, recipe-hash cache, jobs with cancellation, multiplexed SSE,
  potrace.trace core module. 54 tests; ruff + mypy strict clean. Verified live with curl: a real
  400×300 design PNG traced to a 5-path SVG entirely over the HTTP API.
- Contracts frozen so far: ADRs 0002–0007 (transport, auth, sessions/payloads, graph model, cache
  keying, jobs/SSE).
- Multi-node chains already execute (the executor is a real topological walk and the jobs API
  accepts arbitrary DAGs); M1's remaining substance is what's listed under Next.

## Next

M1 work items, in rough order:
1. More core raster modules so multi-node chains are real: crop, rotate, levels, threshold
   (PIL-based, all `raster/png` → `raster/png`), so reorder/invalidation is exercised end to end.
2. Cache invalidation under reorder verified at the API level (M1 exit condition) — test that
   reordering a mid-stack node recomputes only downstream (the executor tests cover this at unit
   level; add an HTTP-level test with the real modules).
3. Draft honored by at least one module (pipeline-boundary downsample per the design doc's Draft
   section — likely a `draft`-aware behavior in the raster modules or a dedicated downsample step).
4. Performance baseline on this machine (trace time, per-edge transport cost, cache hit behavior)
   recorded in docs — replaces the voided design-phase figures (design doc, Open risks).

## Open questions

- CI (GitHub Actions) still unconfigured; the quality gate (pytest + ruff + mypy) runs locally.
  Worth adding once the user confirms pushing to GitHub.
- Draft semantics for raster modules: downsample-at-boundary needs a decision about where the
  boundary node lives (client-built vs. server-injected). Take it as an ADR when M1 reaches item 3.

---
*Last updated: 2026-07-08*
