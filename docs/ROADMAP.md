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
| Boundary trapping for multicolor traces | Candidate | Disjoint color masks are traced independently, so adjacent regions can disagree on their shared boundary — hairline gaps in the merged SVG. Known fix: optional `grow` param on `image.colormask` (dilate N px before tracing = trapping); full Inkscape-style stacking rejected 2026-07-18 (overprints, forces pinned-order rendering everywhere, traces near-whole-canvas per layer). Additive manifest change → needs an ADR when it lands. Gated on a real client trace where seams are visible | — |
| Non-Vector reference extension (agnosticism stress test) | Candidate | A deliberately non-Vector extension in-tree (e.g. batch image processing, or an audio pipeline exercising a non-`raster/*` type) to falsify the "agnostic engine" claim without waiting for a real second consumer. Purpose is to surface real gaps from a real different workload — gaps so surfaced become legitimate roadmap items; this is the bar the design doc sets for scheduling new contract surface. Not a Vector feature, not M5 (M5 is for real external consumers); a cheap internal probe that breaks the "can't get a second consumer without capability, can't justify capability without a second consumer" circularity | — |
| M2: Color (server slice) | Done | Multi-input merges w/ order-aware cache keys (`svg.merge`), parallelized per-color tracing on the thread-pool executor, progressive streaming (disjoint path) exercised by a 16-color trace. [Parallel speedup benchmark](performance-parallel.md) recorded 2026-07-08 | [0009](adr/0009-fixed-arity-ports.md)–[0011](adr/0011-color-separation-modules.md) |
| M3: Extensions (server slice) | Done | Isolated-venv extension installation (`/v1/extensions`, per-extension venv + stdio runner), first out-of-core extension (background removal, rembg). Exit verified 2026-07-09: an extension pinning Pillow below core's version installs into isolation over HTTP and works | [0012](adr/0012-isolated-extension-venvs.md)–[0013](adr/0013-extensions-api.md) |
| M4: Print (server slice) | Done | Pinned-order progressive path: output groups (`outputs[].group` + `groups[].order`) hold overlapping outputs so they stream in declared order. Exit verified 2026-07-09 by test: first-declared output completes last yet emits first | [0014](adr/0014-pinned-order-output-groups.md) |
| M5: Open house | Candidate | LAN binding opt-in w/ enforced token, workspace grouping w/ install-time dependency resolution, cache eviction policy, module-author docs, standalone release. Gated on a non-Vector consumer existing | — |

Note: milestones are one track shared with the Vector client repo — each server capability above
ships alongside the Vector feature that consumes it (per the Design doc), except M5, which
is explicitly for other consumers. Vector-side work is tracked in the Vector repo, not here.

---

## Archive

_Nothing archived yet._
