# ADR 0008: Draft downsampling is a client-built boundary node

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

The design doc (Draft and quality modes) fixes what the server owns: only the draft flag, plumbed
through the protocol and cache keys (ADR 0007). What draft *means* is the pipeline's decision. For
the raster reference workload the strategy is downsampling once at the pipeline boundary so every
downstream module processes fewer pixels for free. The open question was where that boundary
lives: does the server inject a downsample step when draft is on, or does the client build it into
the graph?

## Decision

The client builds the boundary node into the graph: a core module `image.downsample` that is the
identity at full quality and shrinks the image (to a `max_dimension` parameter) when the job's
draft flag is set. The server never injects nodes into a client's graph.

Rationale:
- Server-side injection would require the server to know which type strings are "downsampleable"
  and where the pipeline boundary is — workload knowledge the engine deliberately doesn't have.
- A client that wants a different draft strategy (or none) simply builds a different graph; the
  engine stays neutral.
- The graph a client submits is exactly the graph that runs — no hidden mutations to reason about
  when debugging cache keys or node events.

## Consequences

- `image.downsample` is the first draft-aware module, satisfying the M1 requirement that at least
  one module honors the flag.
- Clients own their draft strategy, consistent with the design doc's position that there is no
  universal downsample.
- Since draft is part of the cache key (ADR 0006/0007), draft and full-quality results never
  cross-contaminate even though the graph shape is identical in both modes.
