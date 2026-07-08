# ADR 0006: Recipe-hash cache keys with content-hashed roots

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

Every module instance's output is cached, keyed on a hash chain (design doc, Caching). The design
doc flags recipe-hash vs. content-hash as an open choice: recipe hashing is cheapest; content
hashing additionally enables early cutoff but interacts badly with nondeterministic modules (ML
inference would produce a new content hash per run, or worse, wrongly reuse one).

Cache keys are internal — not part of any wire contract — so this decision is revisitable without
breaking clients. It still deserves an ADR because the executor's correctness argument depends on
it.

## Decision

- A node's cache key is a **recipe hash**: `H(module_name, module_version, canonical_params,
  input_keys_in_port_order)` where each input key is the cache key of the upstream node's output
  port, or the **content hash** of a bound source payload.
- Source payloads are content-hashed (BLAKE2b) once at first use, so re-uploading identical bytes
  hits the cache.
- Input keys are ordered by the node's declared input port order — multi-input combining is not
  commutative (blend(A,B) ≠ blend(B,A)), so port order is part of the key.
- Canonical params = JSON with sorted keys, no whitespace. Params must be JSON-serializable
  (already guaranteed: they arrive as JSON).
- No early cutoff in this iteration: a changed param always recomputes downstream even if the
  output happens to be identical. Content-hash early cutoff can be layered on later as a pure
  optimization, gated per-module on a declared-deterministic flag.
- The cache is in-memory and unbounded for now. The budget/eviction policy is a known open point
  scheduled for M5; unbounded is acceptable only while the reference workload is a single
  developer's session.

## Consequences

- Editing or reordering one node reruns only what is actually downstream — the M1 exit condition.
- Nondeterministic modules are safe by construction: they are keyed by recipe, so they rerun only
  when their recipe changes, and never poison downstream keys with unstable content hashes.
- Identical work reached via different recipes is not deduplicated (no early cutoff). Accepted
  cost for now.
- Module version is part of the key: upgrading a module correctly invalidates its cached outputs.
