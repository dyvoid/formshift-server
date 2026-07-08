# ADR 0010: Execute independent graph branches concurrently

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

The original executor walked the topological order strictly sequentially. That is correct but
wastes cores on embarrassingly parallel workloads such as multi-color tracing: after posterizing,
each color's mask→trace→colorize branch is independent of the others until the merge tree.

Options considered:

1. **Thread pool inside `execute_graph`**. Simple, keeps the shared in-process cache and session
   payload store accessible without serialization. Python's GIL limits CPU parallelism for pure
   Python, but the dominant work here is PIL/numpy ops and subprocess potrace calls, both of which
   release the GIL.
2. **Process pool inside `execute_graph`**. More parallelism for CPU-bound Python, but every input
   and output would need to be serialized across a process boundary, and the in-memory cache would
   have to be replicated or shared. Premature for the core extension, whose modules are designed to
   run in-process today.
3. **Leave parallelism to module authors**. A module could internally use threads or processes.
That keeps the engine simple but prevents the engine from parallelizing across independent nodes,
which is exactly the M2 pattern.

## Decision

The executor runs independent branches concurrently using a `ThreadPoolExecutor`. The scheduling
rule is: a node becomes ready when all its dependencies have finished; all ready nodes are submitted
to the pool together; as each finishes, newly-ready dependents are submitted. A linear chain still
executes sequentially because only one node is ever ready at a time. The pool size defaults to
`os.cpu_count()` and can be overridden via the `workers` parameter.

The shared state (`node_results`, `node_keys`, `executed`, `cached`, `emitted_outputs`) is guarded
by a single lock. Lock granularity is per completion, not per node, because the dominant cost is the
module execution itself.

Cancellation remains node-boundary: a cancel flag stops dispatching new nodes and waits for
in-flight nodes to finish before raising `ExecutionCancelled`.

## Consequences

- Multi-color tracing (and any other fan-out graph) scales with core count on the host, bounded by
  the number of independent branches.
- The same scheduler handles sequential and parallel graphs with no special cases; a chain is just a
  degenerate parallel graph.
- The cache stays single-instance and in-memory; cache hits are read under the same lock but are
  cheap byte-buffer lookups.
- Out-of-core extension isolation (M3) will likely need a separate process model; this ADR does
  not preclude that. When an isolated module is scheduled, the engine can fall back to sequential
  dispatch per module or wrap it in its own process without changing the branch-level scheduler.
