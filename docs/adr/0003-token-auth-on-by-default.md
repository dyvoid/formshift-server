# ADR 0003: Token auth on by default, including on localhost

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

The intuition that localhost is private is wrong. The 2024 "0.0.0.0 Day" research (Oligo Security)
demonstrated drive-by browser attacks achieving remote code execution against local,
unauthenticated HTTP services (Ray, Selenium Grid, TorchServe as proven targets): any webpage open
in any browser can fire requests at localhost ports. Browsers have blocked the specific 0.0.0.0
vector, but the class (CSRF against local services, DNS rebinding) remains. Formshift Server is a
worse-than-average target: its purpose is executing modules, and its future extension installer
downloads and runs code. Jupyter — the canonical localhost code-execution server — has shipped
token auth on by default for years.

## Decision

- Every request requires `Authorization: Bearer <token>`, compared timing-safe. The only exempt
  endpoint is `GET /health` (it reveals nothing and embedding apps poll it before they have
  captured the token).
- Token sources, in precedence order: `--token` flag, `FORMSHIFT_TOKEN` environment variable. If
  neither is set, the server generates one at startup and prints it with the connection info.
  (A config-file source can be added additively later.)
- The `Host` header is validated against an allowlist — default: localhost forms only
  (`localhost`, `127.0.0.1`, `[::1]`, any port) — blocking DNS rebinding. An `Origin` header, when
  present, must pass the same allowlist; `Origin: null` is rejected.
- Failed auth is `401` with `WWW-Authenticate: Bearer`; failed Host/Origin validation is `403`.
- Binding defaults to `127.0.0.1`. Binding to a non-loopback interface is an explicit opt-in flag,
  and doing so without an explicitly configured token is a **startup error**, not a warning.
- No CORS headers are emitted by default: same-machine native clients don't need them, and their
  absence is itself a browser-side defense. A browser client later means an additive opt-in flag.

## Consequences

- curl and scripts need the token — one copy-paste, printed at startup; embedding apps capture it
  from stdout or pass their own.
- Electron/webview clients that send a real `Origin` must be on the allowlist; extending the
  allowlist is an additive flag when that need arrives.
- Disabling auth is not offered. If an unauthenticated mode is ever demanded, it must arrive as an
  explicit, loudly-documented flag via a new ADR.
