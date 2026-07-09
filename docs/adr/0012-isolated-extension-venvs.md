# ADR 0012: Extensions install into per-extension venvs and run via a stdio runner

- **Status:** Accepted (execution channel superseded by [ADR 0015](0015-persistent-extension-workers.md):
  runner subprocesses are now persistent per-extension workers; format, install, and registry
  decisions here remain in force)
- **Date:** 2026-07-09

## Context

M3 replaces the not-implemented stub behind the manifest's `isolation` field with a real
implementation (design doc, Extensions and dependency isolation). The design commits to tier 2 of
the isolation model: everything outside core defaults to its own isolated environment and process,
because shared environments demonstrably cascade (rembg's NumPy 2.0 breakage, the ComfyUI conflict
reports cited in the design doc).

Decisions needed: the on-disk extension format, how an isolated environment is created, and how the
engine invokes a module it must remain blind to.

Options considered for the execution channel:

1. **Runner subprocess per invocation, JSON over stdio.** No ports, no lifecycle state, no
   partially-alive worker to manage; a crash is an exit code. Cost: interpreter + import time per
   run, and for model-backed modules, model load per run.
2. **Persistent worker process per extension, speaking the server's own HTTP contract.** The design
   doc's stated end state ("spun up on demand, speaking the same HTTP contract"), amortizes model
   load, but needs spawn/health/shutdown/port lifecycle management — meaningful new engine surface.
3. **In-process import with `sys.path` juggling.** Not isolation at all: one interpreter, one
   `sys.modules`, one set of binary wheels. Rejected outright — it is exactly the shared-environment
   failure mode the design documents.

## Decision

**Extension format.** An extension is a source directory: an `extension.toml` manifest (name,
version, description, `isolation`, pinned `requirements`, and one or more `[[modules]]` with typed
ports and an `entry = "file_module:callable"`) plus the Python files implementing the entries. The
entry contract is a plain callable `(inputs: dict[str, bytes], params: dict, draft: bool) ->
{port: (type_string, bytes)}` — extension code imports nothing from formshift_server, so the
engine and the extension share no Python surface, only the manifest and byte streams.

**Install.** `ExtensionManager.install(source)` copies the source under
`<extensions_dir>/<name>/src`, creates `<extensions_dir>/<name>/venv` with stdlib `venv` using the
server's own interpreter, and pip-installs the manifest's pinned requirements into it. A state file
(`installed.json`) is written last, so a crashed install is never mistaken for a complete one;
failures remove the partial directory. Installed extensions reload at startup by re-parsing their
copied manifests.

**Execution.** Option 1: each module run executes `extension_runner.py` (a stdlib-only file from
this package) with the *extension's* interpreter, passing inputs base64-encoded in one JSON request
on stdin and reading one JSON response from stdout. The runner redirects extension stdout to stderr
around the call so print-happy libraries cannot corrupt the response channel. The engine-side
adapter (`IsolatedModule`) implements the same `Module` protocol as core modules, so the executor,
cache, and scheduler are unchanged.

**Registry invariant.** `register()` accepts only `isolation = "core"` manifests;
`register_isolated()` (used by the ExtensionManager) accepts only `"isolated"`. An isolation
declaration is honored by construction, and unknown isolation values remain explicit
`NotImplementedError`s — never a silent shared install. Extension manifests may only declare
`"isolated"` until workspace grouping (M5).

## Consequences

- The exit-condition scenario works: an extension pinning a dependency version that conflicts with
  core installs and runs (verified by the gated `test_extension_conflict_e2e.py`, which pins a
  Pillow major version below core's).
- Process-per-invocation makes model-backed modules pay model-load on every run. This is the known
  cost of deferring option 2; when it matters in practice, a persistent worker can replace the
  runner behind the same `IsolatedModule` adapter without touching the manifest contract or the
  engine. The per-node cache already absorbs repeat invocations with unchanged recipes.
- Base64-over-stdio doubles transport bytes for large payloads. Same story: a shared-memory or HTTP
  channel can replace stdio behind the adapter (transport tiers are already design intent).
- Module version in cache keys is the extension version, so bumping an extension release correctly
  invalidates its modules' cached results.
- The venv inherits the server's interpreter version; an extension needing a different Python is
  out of scope until a real one exists.
