# ADR 0004: Sessions and payload-by-reference transport

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

Interactive parameter changes must never re-send source data; payload transport must survive
client and server being different machines; and the server must hold no implicit global state.
Path-passing (client sends a filesystem path) silently breaks on remote clients; base64-in-JSON
inflates payloads ~33% and defeats streaming.

## Decision

- **Sessions** are the unit of state: `POST /v1/sessions` creates one, `DELETE /v1/sessions/{id}`
  drops it and everything it owns. Every payload and job belongs to an explicit session — no
  implicit global state, session ID in the URL path on every request.
- **Payloads travel as binary bodies** (raw request/response bodies), never base64-in-JSON, never
  filesystem paths.
- **Upload once, reference by ID**: `POST /v1/sessions/{id}/payloads?type=<type-string>` stores
  bytes and returns a payload ID; graphs and jobs reference payloads by ID. Results are payloads
  too, fetched with `GET /v1/sessions/{id}/payloads/{payload_id}` — one transport story in both
  directions.
- Every payload carries a **type string** (e.g. `raster/png`) given at upload; the type string
  names both the data kind and its wire encoding (see the design doc's Modules section).
- Session and payload IDs are server-generated opaque URL-safe strings. Clients must not parse
  them.
- Sessions are in-memory in the current implementation. The contract does not promise persistence
  across server restarts; a client must treat a `404` on a known session as "re-create and
  re-upload."

## Consequences

- Interactive loops are cheap: a parameter change re-sends a small JSON job, not the source image.
- The server owns payload lifetime; the cache budget / eviction open point (design doc, Caching)
  will eventually apply to session payloads as well — the contract already permits eviction
  because persistence was never promised.
- Multipart upload and download of multiple payloads can be added additively if profiling ever
  demands it.
