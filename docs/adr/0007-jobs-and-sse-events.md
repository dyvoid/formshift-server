# ADR 0007: Job lifecycle, cancellation, and the SSE event contract

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

Graph execution can take from milliseconds to minutes; clients need to submit work, watch progress
(including progressive per-node results), and cancel. ADR 0002 fixed the transport (HTTP commands,
one multiplexed SSE channel); this ADR fixes the job and event shapes on top of it.

## Decision

### Endpoints

- `POST /v1/sessions/{sid}/jobs` — body `{"graph": {...}, "draft": false}` (graph per ADR 0005).
  Graph validation runs synchronously: invalid graphs are rejected with `422` and the full error
  list before a job is created. Valid jobs return `201 {"id", "status"}` and execute
  asynchronously.
- `GET /v1/sessions/{sid}/jobs/{jid}` — job status document: `status` is one of
  `pending | running | completed | failed | cancelled`; `outputs` (once completed) lists
  `{node, port, type, payload}` where `payload` is a payload ID fetchable per ADR 0004; `error`
  (once failed) is a human-readable message.
- `DELETE /v1/sessions/{sid}/jobs/{jid}` — request cancellation. Idempotent: `204` whether the job
  was running or already terminal; `404` only if the job doesn't exist. Cancellation takes effect
  at the next node boundary in this iteration (modules are not interrupted mid-run); finer-grained
  interruption can be added later without a contract change.
- `GET /v1/sessions/{sid}/events` — the SSE channel for that session, multiplexing all its jobs.

### Events

SSE with `event:`/`data:` framing, JSON data, every event carrying the job ID. An incrementing
`id:` field is emitted so resume-after-reconnect (`Last-Event-ID`) can be added additively later.

- `job.status` — `{"job", "status"}` on every transition.
- `node.completed` — `{"job", "node", "cached"}` after each node (cache hits included, marked).
- `job.output` — `{"job", "node", "port", "type", "payload"}` as each requested output
  materializes: this is progressive rendering's disjoint path. Outputs are stored as session
  payloads and referenced by ID; bytes never travel over SSE.
- `job.completed` / `job.failed` / `job.cancelled` — terminal, `job.failed` carries `error`.

Comment lines (`: keepalive`) are sent periodically to hold idle connections open. Unknown event
types must be ignored by clients (forward-only rule).

### Draft flag

`draft` is plumbed through the whole chain now (job body → executor → module run), and is part of
the cache key (a draft result must never be served for a full-quality request). No current module
implements draft behavior; per the design doc, such modules simply run at full cost, which is the
defined behavior.

## Consequences

- Results travel exactly one way (payload upload/download), keeping SSE lightweight and making
  progressive rendering a pure notification concern.
- Node-boundary cancellation means a long-running single module cannot yet be interrupted; the
  potrace reference workload's nodes are short, and module-level interruption is an internal
  improvement, not a contract change.
- Job records live in the session (in-memory, ADR 0004's non-persistence applies).
