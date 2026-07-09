# ADR 0015: Persistent per-extension worker processes

- **Status:** Accepted (supersedes the process-per-invocation channel of ADR 0012)
- **Date:** 2026-07-09

## Context

ADR 0012 executed each isolated-module run as a fresh runner subprocess. That was the simplest
correct thing, and its recorded consequence arrived immediately: the first real extension
(background removal) is model-backed, and process-per-run makes it pay interpreter start, library
import (onnxruntime is not small), and model load on every invocation — hostile to the interactive
dial-turning workload this server exists for. ADR 0012 explicitly reserved the upgrade path:
replace the channel behind the `IsolatedModule` adapter without touching the manifest contract or
the engine.

## Decision

One long-lived worker process per installed extension, started lazily on first use, serving
newline-delimited JSON requests over stdio (same request/response shapes as before — the framing
gained only a newline). All of the extension's modules share its worker; module-level state in
extension code (imports, model sessions) now legitimately amortizes across runs, and the
background-removal module caches its ONNX session per model name.

Lifecycle rules, all engine-side in `ExtensionWorker`:

- **Serialization.** One lock per worker: an extension's modules never run concurrently inside it,
  keeping a single copy of model memory and making extension code trivially thread-free. Different
  extensions have independent workers, so cross-extension graph parallelism is unaffected.
- **Failure.** An ordinary module exception is a JSON error response; the worker lives on. A
  worker that dies (crash, OOM-kill) or hangs (per-request watchdog kills it at the same timeout
  as before) fails that one run with a `ModuleError` and is respawned on the next request.
- **Protocol hygiene.** The runner claims the real stdout for protocol frames and points fd 1 at
  stderr before any extension code runs — an fd-level guard, so even native libraries that write
  to stdout can't corrupt the channel. A response that still fails to parse kills the worker so
  the next request starts clean.
- **Shutdown.** Workers are killed via `atexit`; there is no idle reaping until memory pressure is
  a demonstrated problem (single-user local server, one worker per installed extension).

## Consequences

- Model-backed modules load their model once per server lifetime instead of once per run; for
  rembg-class extensions that is the difference between interactive and not.
- Per-run cost drops to one JSON round-trip over pipes for every isolated module.
- An extension's own modules serialize. If per-extension parallelism is ever needed, a worker pool
  behind the same `ExtensionWorker.request` signature is the additive path — but it multiplies
  model memory, so it should wait for a real demand.
- Extension state can now leak across runs within one extension (a global mutated by one request
  is visible to the next). The module contract already demands determinism for caching, so this
  changes exposure, not rules; the hard reset is still available by restarting the server.
- Worker stderr is discarded rather than captured per-run (with a shared long-lived process,
  attributing stderr to one request is no longer meaningful). Error messages now come from the
  runner's structured response, which the fixture-crash tests confirm is the more useful channel.
