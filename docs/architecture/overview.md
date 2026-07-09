# Architecture Overview

## What this is

Formshift Server is a standalone module execution engine: an HTTP process exposing a DAG of typed
processing units, with per-node caching, progressive results, and network-transparent execution.
Its contract is open on three axes (data types, module implementation language, clients) and
opinionated on a fourth: it executes one-shot, cached, interactive pipelines, and nothing else.

This document summarizes the shape for orientation. [Design](design.md) is the authoritative
design source — read it for full rationale; this doc should stay consistent with it, not duplicate
it wholesale.

## Shape

```
Client (HTTP)
   │  upload payload → session ID
   │  POST job (graph: nodes + typed edges)
   ▼
┌─────────────────────────────────────────────┐
│ Formshift Server                             │
│                                               │
│  Session/Auth ── HTTP API ── SSE (progress)  │
│                     │                        │
│              DAG Executor                    │
│           (topological walk)                 │
│                     │                        │
│         ┌───────────┼───────────┐            │
│         ▼           ▼           ▼            │
│      Module A    Module B    Module C        │
│    (core, in-  (local, out-  (remote,        │
│     process)    of-process)   bytes-over-     │
│                                wire)          │
│                     │                        │
│               Hash-chain Cache               │
│         (per-node, keyed on params +         │
│          upstream input hashes)              │
└─────────────────────────────────────────────┘
```

## Key components

- **HTTP API** — discrete request/response operations (session creation, payload upload by
  reference, job submission, cancellation via `DELETE`). Stateless, debuggable with curl.
- **SSE channel** — one multiplexed stream per client (not per job) for progress push during
  long-running jobs, keyed by job ID.
- **DAG executor** — walks the graph topologically; a single-node graph is the degenerate case of
  the general executor, not a separate code path.
- **Modules** — black-box processing units, out-of-process, identified purely by typed I/O ports.
  A type string (e.g. `raster/png`, `vector/svg`) implies both a data kind and a wire format by
  convention. Ports are strictly type-checked at connection time, at the protocol level (server
  enforces it, not each client).
- **Cache** — keyed on a hash chain (a module instance's own params + hash of upstream inputs).
  Reordering or editing one instance reruns only what's actually downstream.
- **Transport tiers** — one logical contract, three physical channels negotiated by module
  co-location: in-process function call (core), local shared-memory handle (out-of-process local),
  bytes over the wire (remote). See the design doc's Transport tiers section before touching this.
- **Extensions / isolation** — modules ship in installable extensions with their own declared
  dependencies. Three isolation tiers: shared core env, per-extension isolated venv by default,
  workspace-level grouping as an explicit opt-in. See the design doc's Extensions section.

## Data / control flow

1. Client uploads source payload once to a session; gets an ID back.
2. Client submits a job: a graph (node instances + typed edges) referencing that ID and any
   per-node parameters.
3. Executor topologically walks the graph. For each node: compute the hash-chain cache key: if hit,
   reuse the cached output; if miss, dispatch to the module via the appropriate transport tier.
4. As each node's output materializes, it streams to the client over SSE (progressive rendering) —
   immediately if outputs are disjoint, in pinned order if outputs are designed to overlap.
5. Client can cancel an in-flight job via `DELETE` at any point.

## Python structure

- **Package layout:** `src/formshift_server/` (PyPA `src/` layout).
- **Entry point:** CLI (`formshift-server --port ...`) that starts the HTTP+SSE server as an
  ordinary standalone process — no assumption of a parent process or co-located client.
- **Core extension:** the classical CV stack (PIL, numpy, scipy, scikit-image) runs in the main
  package's own environment; it is architecturally just an extension, not specially privileged in
  the engine, only in default packaging.
- Everything else (out-of-core extensions) runs in its own venv and process: installed via
  `POST /v1/extensions` into a per-extension venv, executed per-invocation through a stdio runner
  the engine is otherwise blind to (ADRs 0012–0013). A persistent per-extension worker speaking
  the HTTP contract is the designed end state; the runner is the current transport behind the
  same adapter.

## Constraints

- **No streaming/timeline media, no realtime processing, no cross-module GPU residency, no job
  scheduler.** These are explicit non-goals (see the design doc's "What this engine is and is not"),
  not gaps to quietly fill in later without a product decision to widen scope.
- **Token auth is on by default, including on localhost.** Binding beyond `127.0.0.1` is an
  explicit opt-in and a startup error without a configured token. See the design doc's Security
  section before touching auth or binding defaults.
- **Payloads never travel as base64-in-JSON or shared filesystem paths** — binary bodies only,
  upload-once-reference-by-ID. Path-passing breaks the moment client and server are different
  machines.
- **potrace is invoked as a subprocess only** (aggregation, not linking) — this is a licensing
  boundary (GPL-2.0), not a performance choice. Do not switch to a linked binding.
- Performance-driven decisions (transport tiers, cache sizing, interactivity budgets) rest on
  structural arguments until the M1 hardware baseline exists (see Open risks in the design doc); design
  figures from before that baseline are void.

## Decisions

The reasoning behind specific choices lives in the [ADR log](../adr/). Start there before changing
anything structural. The design doc's Build Strategy section governs what counts as a "frozen
contract" requiring an ADR versus an internal implementation detail that's free to churn.
