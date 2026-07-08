# ADR 0011: Color-separation modules live in core

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

Multi-color tracing needs a server-side pipeline that turns one raster image into N color layers
and then merges them into a single SVG:

```
posterize -> (mask -> trace -> colorize) per color -> merge tree -> layered SVG
```

This could be built in several places:

1. **Core modules**. The operations are classical image processing (PIL quantize/mask) and trivial
   SVG attribute manipulation. They fit the same dependency profile as the existing `image.*`
   modules.
2. **A single monolithic module** such as `vector.color_trace` that takes an image and a palette and
   returns the merged SVG. That hides the intermediate caching opportunities and forces the client
   to give up control over per-color parameters (e.g. per-color turdsize).
3. **Client-side only**. The client could run posterize/mask/colorize/merge itself and only ask the
   server to trace each mask. That contradicts the server's role as the execution engine and would
   duplicate module behavior in the client.

## Decision

Add four small core modules that compose into the pipeline above:

- `image.posterize` — quantize RGB to N flat colors, output a palette-mode PNG. The palette is
  exposed through the PNG so any decoder can map indices to RGB.
- `image.colormask` — extract one palette index as a binary mask (black = selected color,
  white = background), ready for `potrace.trace`.
- `svg.colorize` — set the `fill` attribute on the top-level groups and paths of an SVG.
- `svg.merge` — stack two SVGs, `under` then `over`, taking the canvas from `under`.

The N-way merge composes as a binary tree of `svg.merge` nodes (ADR 0009). The per-color branches
run concurrently on the parallel executor (ADR 0010).

## Consequences

- Every intermediate step (posterized image, each mask, each trace, each colorized layer, each
  partial merge) is individually addressable and cacheable. Editing one color's parameters only
  recomputes the path from that leaf to the root.
- Clients retain full control: they choose the palette, the number of colors, per-color trace
  parameters, and the merge order.
- The modules operate on `raster/png` and `vector/svg` wire types, so they stay within the existing
  contract and do not introduce new type strings.
- `svg.colorize` and `svg.merge` are intentionally scoped to potrace-generated SVG (a single top-level
  group wrapping paths). They do not attempt to handle arbitrary SVG features such as `defs`, CSS
  styles, or nested transforms beyond the group's own transform.
