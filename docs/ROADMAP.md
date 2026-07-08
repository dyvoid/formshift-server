# Roadmap

This is the "what might come next" document for the server. It is not a sprint board or a
commitment list. Anyone should be able to scan it without archaeology.

Status values:
- **Candidate** — idea worth tracking; no decision made yet
- **Planned** — decision made, not started; ADR exists or is in progress
- **In flight** — actively being worked on; see [PICKUP.md](../PICKUP.md) for current state
- **Done** — shipped; kept here for a while for context, then archived

Milestones below are defined in the Milestones section of
[Design](architecture/design.md). Each has a testable exit condition, not a date — see that
document for full detail; this table tracks status only. The full server design (contracts,
caching, security, isolation model, etc.) also lives there, not restated here.

| Feature | Status | Description | ADR |
|---|---|---|---|
| M0: Trace (server slice) | Done | HTTP API w/ token auth + sessions, linear DAG executor, hash-chain cache, single potrace module in core env. Exit verified 2026-07-08: PNG → usable SVG entirely over HTTP against the real binary | [0002](adr/0002-http-plus-multiplexed-sse.md)–[0007](adr/0007-jobs-and-sse-events.md) |
| M1: Pipeline (server slice) | Done | Multi-node chains, cache invalidation under reorder (HTTP-level test), draft honored by image.downsample, [performance baseline](performance-baseline.md) recorded 2026-07-08 | [0008](adr/0008-draft-as-client-built-boundary-node.md) |
| Raw-buffer interchange for co-located modules | Candidate | Baseline shows ~129 ms/node PNG codec cost at 3000×2250; a raw-buffer type (reserved `raster/rgba8`) behind the same contract is the known fix. Profile a real client workload first | — |
| M2: Color (server slice) | Done | Multi-input merges w/ order-aware cache keys (`svg.merge`), parallelized per-color tracing on the thread-pool executor, progressive streaming (disjoint path) exercised by a 16-color trace. [Parallel speedup benchmark](performance-parallel.md) recorded 2026-07-08 | [0009](adr/0009-fixed-arity-ports.md)–[0011](adr/0011-color-separation-modules.md) |
| M3: Extensions (server slice) | Candidate | Isolated-venv extension installation implemented; first out-of-core extension (background removal) | — |
| M4: Print (server slice) | Candidate | Pinned-order progressive path for overlapping outputs | — |
| M5: Open house | Candidate | LAN binding opt-in w/ enforced token, workspace grouping w/ install-time dependency resolution, cache eviction policy, module-author docs, standalone release. Gated on a non-Vector consumer existing | — |

Note: milestones are one track shared with the Vector client repo — each server capability above
ships alongside the Vector feature that consumes it (per the Design doc), except M5, which
is explicitly for other consumers. Vector-side work is tracked in the Vector repo, not here.

---

## Archive

_Nothing archived yet._
