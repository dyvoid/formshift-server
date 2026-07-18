# ADR 0016: Move vector modules out of core into a separate extension

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

The design defines Core as "one shared environment for the common classical CV stack (PIL, numpy,
scipy, scikit-image)" — see the Extensions and dependency isolation section of
[Design](../architecture/design.md). The shipped `core/` package violates this definition:

- `potrace.trace` is a copyleft GPL-2.0 external binary invoked via `subprocess.run` (aggregation,
  not linking — a licensing boundary, not a classical-CV operation). It uses none of PIL/numpy/
  scipy/scikit-image for its core work; PIL is used only to convert PNG→PGM before handing off.
- `svg.merge` and `svg.colorize` are Vector-shaped SVG operations, not classical CV. They exist
  because multicolor tracing (M2) needed them.

They were placed in `core/` as a build-sequence artifact: M0's exit condition required a tracer
available by default, and at M0 no isolated-extension mechanism existed yet, so core was the only
place to put one. That was a build-sequence choice, not an architectural fit, and it has been wrong
since the moment M3 made isolated extensions real.

This is a direct contradiction of the project's agnostic-engine thesis. `default_registry()` in
`app.py` hardcodes the full core set with no knob to exclude them, so a non-Vector consumer wanting
`Crop`/`Rotate`/`Threshold` gets the vectorizer and SVG helpers loaded into their registry whether
they want them or not. The design says "clients typically bundle and enable [core] by default as a
packaging choice, which is a different fact from being structurally privileged" — but the current
code makes no such choice available.

## Decision

`potrace.trace`, `svg.merge`, and `svg.colorize` move out of `core/` into a separate first-party
extension maintained in this repo. Core becomes strictly the classical CV stack: raster operations
on `raster/png` using PIL/numpy/scipy/scikit-image. Nothing vector-specific, nothing copyleft,
nothing subprocess-shelled-out remains in core.

`default_registry()` in `app.py` becomes configurable so clients choose which first-party
extensions to enable. The default bundling remains a packaging choice the design describes, not a
structural privilege baked into the engine.

The architectural decision is final and unambiguous. Implementation timing follows the build
strategy — the split lands when work on it begins, not gated on a future consumer — but the
*decision* is made now and is not reversible. Any future agent reading `core/` and seeing no
vector modules there must understand that as deliberate, not as "nobody's gotten to it yet."

## Consequences

- Core's scope now matches its design-doc definition. The agnostic-engine thesis is no longer
  contradicted by the shipped code.
- A non-Vector consumer no longer gets vectorizer modules loaded into their default registry.
  `default_registry()` exposes the bundling knob the design always described.
- `potrace`'s GPL-2.0 subprocess boundary becomes an extension-level concern, isolated from the
  permissively-licensed core. The licensing boundary itself (subprocess aggregation, not linking)
  is unchanged — only its location in the package structure moves.
- The split is a packaging and refactor change behind already-frozen contracts (module manifest
  format, HTTP API, type-string registry, session semantics). No contract breaks. No new ADRs
  required for the manifest or API surface.
- Existing tests that assume `potrace.trace` / `svg.merge` / `svg.colorize` are in
  `default_registry()` must be updated to either register the new extension explicitly or assert
  against a registry that includes it.
- M0's historical exit condition ("tracer available by default") was satisfied by the build-sequence
  placement at the time. That condition is historical, not a forward constraint — the tracer being
  available by default was a Vector-bundling choice, which under this ADR becomes exactly the kind
  of packaging choice the design describes, made by the client that needs it.
- The new extension is first-party (maintained in this repo, shipped alongside the server) but
  architecturally just another extension. Nothing in the engine special-cases it. This is the same
  status `core/` already has per its own module docstring: "Architecturally just an extension like
  any other, nothing in the engine special-cases it."
- The Open risks bullet "Core extension scope drift" in
  [Design](../architecture/design.md) is resolved as a decision; the implementation remains as
  work-to-be-done under this ADR.
