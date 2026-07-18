# ADR 0017: Domain extensions live in their own repositories

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

ADR 0013 defined the extensions API and install path: extensions are source directories with an
`extension.toml` manifest, installed via `POST /v1/extensions` into a `--extensions-dir`, each
getting its own isolated venv. The mechanism is repo-agnostic by construction — the server is blind
to where extension source lives.

In practice, the only extension written so far (`extensions/background-removal/`) was placed in-tree
in the server repo, and ADR 0016 as originally drafted proposed moving the vector modules into "a
separate first-party extension maintained in this repo." That framing is wrong. It conflates two
different things:

- **Core** — the classical CV stack the server ships with and that clients bundle by default as a
  packaging choice. In-tree by definition; it shares the server's own environment.
- **Domain extensions** — modules for a specific domain (SVG tracing, background removal, anything
  future). These are reusable artifacts in their own right. potrace is used by Inkscape, CNC
  software, and font tooling; rembg is used by countless image pipelines. Neither is a Formshift
  concept. Tying them to the server repo implies the server project owns them, which it doesn't —
  and which it shouldn't, because the whole point of the agnostic-engine thesis is that the server
  doesn't know what domains its modules serve.

This is the ComfyUI custom-nodes model, applied deliberately: the engine ships the engine and core;
extensions are independently owned, discovered, and installed. The difference is that this project's
extensions also get per-extension venv isolation (ADR 0012), which ComfyUI's don't — so the model
is strictly stronger, not weaker.

## Decision

Domain extensions live in their own git repositories, not in-tree in the server repo. The server
repo ships:

- The engine (`src/formshift_server/`).
- Core (`src/formshift_server/core/`) — strictly the classical CV stack, per ADR 0016.
- Tests, docs, build config, the dev `tools/` directory.

It does not ship domain extensions. The existing `extensions/background-removal/` directory moves
to its own repo. The vector modules covered by ADR 0016 move to their own repo. Any future domain
extension starts in its own repo, not in-tree.

The server remains blind to where extension source lives — the install API (ADR 0013) takes source
and installs it; it does not care about provenance. Discovery, versioning, and distribution of
extension repos are out of scope for this server project; they are the extension author's concern,
exactly as ComfyUI does not own the custom-node ecosystem.

Core is the one structural exception: it lives in-tree because it shares the server's own
environment (no isolated venv) and is bundled by clients as a packaging choice. This exception is
narrow and does not extend to any domain extension, however "obvious" or "first-party" it seems.

## Consequences

- The server repo stays focused on the engine. Domain code lives where domain code belongs —
  owned by whoever maintains that domain, versioned on its own cadence.
- A consumer who wants a domain (SVG tracing, background removal, anything) installs that
  extension's repo through the API. A consumer who doesn't, doesn't. No domain code is forced into
  a default registry by virtue of living in the server repo.
- Extension authors own their own release cycle, dependency pins, issue tracker, and licensing
  decisions independently of the server project. A copyleft extension (e.g. one wrapping potrace)
  does not create licensing pressure on the server repo.
- The existing `extensions/background-removal/` directory is now in the wrong place and must move
  out. Its tests (`tests/test_removebg_e2e.py`, the conflict-pin e2e in
  `tests/test_extension_conflict_e2e.py`) need to either move with it or become tests that install
  from the new repo location. Tracked as in-flight work alongside ADR 0016's implementation.
- The M3 exit condition ("first out-of-core extension: background removal, rembg") remains
  historically satisfied — the extension existed and worked. Its in-tree placement was a
  build-sequence choice, not a forward constraint, same as potrace's placement in core.
- Discovery (a registry, a listing, a search API) is explicitly out of scope for the server.
  ComfyUI's custom-node discovery lives outside ComfyUI itself (the registry site, the manager
  extension); the same shape applies here. If a discovery layer ever becomes wanted, it's a
  separate project, not server contract surface.
- No contract break. The extension manifest format, install API, and isolation model (ADRs
  0012–0013) are unchanged. This is a repo-organization decision, not a protocol decision.
