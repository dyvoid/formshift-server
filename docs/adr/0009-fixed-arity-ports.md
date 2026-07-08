# ADR 0009: Ports have fixed arity; N-way operations compose as trees

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

Multi-color tracing needs N-way combination (merge N traced color layers into one SVG), and N is a
runtime parameter. The graph contract (ADR 0005) declares a module's ports statically in its
manifest. Two ways to reconcile that: variadic input ports (a manifest field marking a port as
accepting 1..N connections), or fixed-arity ports with N-way operations built as a composition of
binary nodes.

## Decision

Ports keep fixed arity. An N-way merge is a client-built tree of binary `svg.merge` nodes
(depth ⌈log₂N⌉, N−1 nodes for N inputs). Merging is associative for layer stacking, so the tree
shape doesn't change the result.

Rationale:
- The "every input fed exactly once" validation rule (ADR 0005), the port-order-sensitive cache
  key (ADR 0006), and the type checker all stay exactly as shipped; variadic ports would
  complicate all three (what is "port order" for a variadic port? how does the cache key encode
  arity?).
- A merge tree parallelizes naturally: independent subtrees run concurrently on the parallel
  executor, whereas one N-input node is a synchronization point that must wait for all N inputs.
- Graphs are data built by clients; generating a balanced tree is a few lines of client code, not
  a UX burden on any human.

Variadic ports remain possible as a purely additive manifest capability later (a new optional
field, ignored by old servers is not an option — servers validate — but a new protocol capability
flag is); if that day comes, it needs its own ADR and a demonstrated workload that trees genuinely
cannot serve.

## Consequences

- 16-color merge = 15 binary nodes. Node count grows linearly with color count; per the M1
  baseline the per-node overhead is codec-dominated for raster types, but `vector/svg` payloads
  are small text — merge nodes are cheap.
- Every merge step is individually cached: editing one color's trace parameters re-merges only
  the path from that leaf to the root, not the whole tree.
