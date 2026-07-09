# ADR 0013: Extension install API — explicit opt-in, local source, synchronous

- **Status:** Accepted
- **Date:** 2026-07-09

## Context

ADR 0012 gives the server an extension installer; clients need a way to drive it. This adds
frozen contract surface, so the shape is deliberately minimal (build strategy: freeze the minimum
surface). Three questions: how the capability is enabled, where extension sources come from, and
whether installation blocks the request.

## Decision

**Opt-in by configuration.** Extension installation is disabled unless the embedding app passes
`--extensions-dir` (config `extensions_dir`). Installing an extension executes downloaded code;
that capability should exist only when the operator asked for it. With no directory configured,
`POST /v1/extensions` returns 503 and `GET /v1/extensions` reports `"enabled": false` so clients
can feature-detect without probing.

**Contract.**

- `GET /v1/extensions` → `{"enabled": bool, "extensions": [{name, version, description,
  isolation, modules: [module names]}]}`.
- `POST /v1/extensions` with `{"path": "<local source directory>"}` → 201 with
  `{name, version, modules}`; 409 when the extension or a module name is already present; 422 for
  an invalid source or manifest; 503 when disabled.
- Installed extensions' modules appear in `GET /v1/modules` (with their real `isolation` value)
  and are referenced in graphs like any other module. No new job-side surface.

**Local paths only, for now.** The client (which on the target deployment shares the machine)
stages the extension source and passes its path. Fetching from URLs/marketplaces adds transport,
verification, and trust questions that belong to a milestone with a real consumer for them; the
`{"path": ...}` body leaves room to add a `url` variant additively later.

**Synchronous install.** The POST returns when venv creation and dependency download finish —
possibly minutes for wheel-heavy extensions. The alternative (an async install-job with progress
events) is real surface that duplicates the job/SSE machinery for a rare, operator-initiated
action. If installs need progress reporting once real extensions are in use, an additive
`?async=1` variant can reuse the events channel; starting synchronous freezes less.

## Consequences

- The embedding client (Vector) controls both the directory and when installs happen; a standalone
  operator gets the same behavior from the flag. Nothing installs behind anyone's back.
- A slow install occupies one request for its duration (it runs in a worker thread, so the event
  loop and other requests are unaffected). Clients should use a generous request timeout for POST.
- The auth model is unchanged: install requests carry the same bearer token as everything else.
  Token-holders could already execute arbitrary code through modules-plus-payloads by design
  (Jupyter-class trust, ADR 0003); this endpoint does not change that boundary, but it does make it
  more legible — which is why the capability is opt-in.
- Uninstall/upgrade endpoints are deliberately absent until something needs them; delete the
  extension's directory and restart, for now.
