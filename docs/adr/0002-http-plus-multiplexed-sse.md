# ADR 0002: HTTP + one multiplexed SSE channel, versioned under /v1

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

The server needs a client-facing protocol that any frontend can speak, that is debuggable with
curl, and that supports server-to-client progress push during long-running jobs. Peers in this
space (ComfyUI, Jupyter, the FBP protocol) all chose WebSocket. Browsers (including Electron's
Chromium renderer) cap HTTP/1.1 connections at six per origin, which rules out one push connection
per job.

## Decision

- Discrete operations are plain HTTP request/response. No RPC framing, no WebSocket commands.
- Progress push is **SSE (Server-Sent Events)**: the push is genuinely one-directional, and
  commands (including cancellation, a first-class `DELETE` on the job) travel the other way as
  plain HTTP.
- **One multiplexed SSE channel per client** (scoped to a session), not one per job. Events carry
  job IDs.
- All contract endpoints live under a **`/v1` path prefix**. `GET /health` sits outside the
  version prefix (it must stay stable across protocol versions for embedding apps that poll
  readiness).
- Forward-only evolution: unknown JSON fields are ignored, never rejected; new capabilities are
  opt-in additions; a breaking change means a new version prefix, which we intend never to need.

## Consequences

- Everything is curl-debuggable; no client library is required.
- Divergence from every peer's WebSocket choice is deliberate and documented; if a genuinely
  bidirectional need appears later, a WebSocket endpoint can be added additively without breaking
  the SSE contract.
- The six-connections-per-origin browser cap is respected by construction.
- Version prefix commits us to never breaking `/v1` once shipped — the build strategy's
  forward-only rule.
