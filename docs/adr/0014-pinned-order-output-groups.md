# ADR 0014: Output groups with pinned emission order

- **Status:** Accepted
- **Date:** 2026-07-09

## Context

Progressive rendering has two safety regimes (design doc, Progressive rendering). Disjoint outputs
can stream in completion order — shipped in M2 as the `job.output` event flow. Outputs that
deliberately overlap (a white underbase layer beneath ink colors in print separation) cannot: if a
later layer arrives before what it stacks on, the client shows a wrong composite. The design
requires a second, pinned-order path decided per output group, not a single generalized one.

Options for where order is enforced:

1. **Client-side reordering.** Every client reimplements buffering, and the server contract stays
   silent about a semantic the workload requires — the wrong-composite bug becomes a per-client
   trap rather than an impossibility.
2. **Server-side hold in the executor.** The executor's job is dependency scheduling; emission
   order is a presentation concern, and burying it there couples scheduling to it.
3. **Server-side hold at the job/event layer.** The executor keeps completing nodes in whatever
   order the schedule allows; the job layer gates `job.output` emission. Chosen.

## Decision

**Contract (additive to ADRs 0005/0007).** An output entry may carry `"group": "<id>"`, and the
graph may declare `"groups": [{"id", "order"}]` with `order` one of `"completion"` (default
behavior, group is annotation only) or `"pinned"`. Validation rejects undeclared group references,
duplicate group ids, and unknown order values (explicit rejection, never silent acceptance).
`job.output` events and the terminal job document's `outputs` list carry `"group"` for grouped
outputs. Ungrouped outputs are untouched — existing clients see identical behavior.

**Semantics.** Within a pinned group, outputs are emitted in the order they appear in the graph's
`outputs` list; a member that computes early is held until every member declared before it has
been emitted. Different groups (and ungrouped outputs) never block each other. Node scheduling,
caching, and `node.completed` events are completely unaffected — only `job.output` emission (and
therefore payload availability announcements) is gated.

**Implementation.** A small gate in `JobManager._run`: per pinned group, an expected sequence, a
held-buffer, and a cursor, flushed under one lock so concurrent branch completions cannot
interleave a group's emission order.

## Consequences

- The print-separation workflow gets its guarantee from the server: a client that renders
  `job.output` events as they arrive composes correctly by construction.
- A pinned group's total latency to last-output is unchanged (nodes still run in parallel); only
  intermediate visibility is traded, which is exactly the point.
- If a mid-group node fails or the job is cancelled, members after the gap are never emitted even
  when computed — for overlapping outputs a partial prefix is the only safe partial result. Their
  payloads simply don't get announced; the job's terminal status tells the client why.
- Order is per-graph data, so the same modules can serve both regimes without variants.
