# ADR 0005: Graph data model — typed ports, explicit edges, payload bindings

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

The engine executes a DAG of module instances even when a client only presents a linear stack
(design doc, Execution model). The graph wire format is a frozen contract: clients build it, the
server validates it at the protocol level so every client gets the same guarantees.

## Decision

A job's graph is JSON with four parts:

```json
{
  "nodes":    [{"id": "trace", "module": "potrace.trace", "params": {"blacklevel": 0.45}}],
  "edges":    [{"from_node": "a", "from_port": "out", "to_node": "trace", "to_port": "image"}],
  "bindings": [{"payload": "<payload-id>", "node": "a", "port": "image"}],
  "outputs":  [{"node": "trace", "port": "svg"}]
}
```

- **Nodes** are module instances: client-chosen unique `id`, module name, free-form `params`
  object (validated by the module, opaque to the graph layer).
- **Edges** connect one node's output port to another node's input port, all four coordinates
  explicit. Named typed ports, never an implicit single input.
- **Bindings** attach uploaded payloads (ADR 0004) to input ports — how source data enters the
  graph.
- **Outputs** name which node output ports become result payloads. Nothing is returned implicitly.

Validation, server-side, before execution starts:

- Node IDs unique; modules must exist in the registry.
- Every edge endpoint must name an existing node and port.
- **Strict type matching**: an edge's `from` port type string must equal its `to` port type
  string exactly; a binding's payload type must equal the port type exactly. Open namespace,
  strict matching (design doc, Modules).
- Every input port is fed exactly once (by an edge or a binding) — no dangling or doubly-fed
  inputs.
- The graph must be acyclic.

Errors are reported as a `422` with a list of human-readable validation messages, before any
module runs.

## Consequences

- A linear stack is the degenerate case: same format, edges forming a chain.
- Multi-input modules (M2) need no contract change — the format already carries them.
- Params being opaque to the graph layer means module-level param validation errors surface at
  execution time, not validation time; a params-schema field in manifests can be added additively
  later.
