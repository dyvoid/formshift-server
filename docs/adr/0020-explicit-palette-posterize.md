# ADR 0020: Explicit-palette posterize

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

`image.posterize` (ADR 0011) quantizes RGB to N flat colors via PIL's median-cut and emits a
palette-mode PNG. The palette is exposed through the PNG so any decoder — including
`image.colormask` — can map indices to RGB. The client's multicolor pipeline relies on a stable
index↔fill contract: indices `0..N-1`, one `image.colormask` branch per entry, one `svg.colorize`
fill per branch.

Median-cut is frequency-weighted: it allocates clusters by pixel count. Small-but-semantically-
important regions get absorbed into neighboring clusters regardless of how large N is. A real
Vector case: a cat portrait's green eyes are ~0.1% of pixels and never survive posterize even at
`colors: 32` — median-cut merges them into the surrounding fur cluster every time. No choice of N
fixes this; the algorithm cannot know which small regions matter to the user.

The client flow this blocks is two-phase: phase 1 runs auto-posterize to *propose* a palette
(existing behavior), the user pins/adds/removes swatches in the UI, phase 2 re-runs with the
edited palette. The auto path stays load-bearing — it is how the palette is proposed. The explicit
palette is a refinement pass over it, not a replacement. What is missing is a way for phase 2 to
say "use exactly these colors, in this order" instead of "find N colors."

## Decision

**Contract (additive to ADR 0011).** `image.posterize` gains an optional `palette` param: a list
of `#rrggbb` hex strings, mutually exclusive with `colors`. Validation:

- `palette` and `colors` must not both be present (explicit 422, never silent acceptance).
- Neither present → existing behavior (`colors: 8` default). Existing clients are untouched.
- `palette` length in `[2, 256]` (matches the `colors` range and the PNG PLTE limit; a single-entry
  palette is a degenerate flood-fill the client can do without this module).
- Each entry is a valid `#rrggbb` hex string (same validation as `svg.colorize`'s `fill`).
- No duplicate entries — duplicates would collapse two indices onto one color and muddy the
  index↔fill contract (the client expects one colormask branch per entry).

**Semantics.** When `palette` is given, clustering is skipped entirely. Each pixel is mapped to
the nearest palette entry by perceptual distance, and the output is a palette-mode PNG whose PLTE
is the supplied list **in the given order**. Distance metric: CIELAB (convert both the pixel and
the palette entries to Lab, take Euclidean distance), which is perceptually correct and within
core's dependency profile (scikit-image's `rgb2lab`). Weighted RGB is an acceptable implementation
fallback only if Lab proves prohibitively costly on target hardware; the metric choice is
implementation detail, not contract — but Lab is the target, and the choice must be deterministic
per `module_version` so cache keys stay stable (ADR 0006). Ties break to the lowest index, also for
determinism.

The PLTE order is the contract-relevant part: indices `0..N-1` correspond to `palette[0..N-1]` in
order, so `image.colormask` (ADR 0011) works unchanged — one branch per index, one `svg.colorize`
fill per branch, exactly as in the auto path. The only thing that changes is who picks the palette
and in what order.

**Cache keys.** ADR 0006 keys on `canonical_params` (sorted JSON, no whitespace), so a node with
`palette` and a node with `colors` get distinct keys automatically, and two different palettes get
distinct keys. No cache-key change is needed; the new param is handled for free.

**Out of scope of this ADR — default quantizer upgrade.** Separately, the default `colors: N` path
could adopt a better quantizer (PIL's `MAXCOVERAGE`, k-means in Lab, or a libimagequant-class
algorithm) as a general quality win for gradients. This is a nice-to-have implementation
improvement *behind the already-frozen `colors` contract* — no new contract surface, no ADR
required when it lands (same regime as `image.invert`: new behavior behind a frozen contract). It
is explicitly **not** a substitute for the explicit-palette path: no frequency-weighted algorithm
can know which small regions matter, which is the whole problem this ADR solves. Recording it here
only so it is on the record as a known follow-up, not as part of the frozen contract.

## Consequences

- Small, semantically-important regions survive posterize when the user pins them — the cat's
  green eyes stay green because the user-supplied palette includes that green and nearest-color
  mapping does not care about pixel frequency.
- The auto path (`colors`) remains load-bearing for palette *proposal*; explicit palette is the
  refinement pass. The two are mutually exclusive at the param level but compose across the two
  phases of the client flow.
- The index↔fill contract from ADR 0011 is preserved by construction: PLTE order is the supplied
  order, `image.colormask` and `svg.colorize` are unchanged. No existing client breaks.
- New contract surface on a frozen module manifest is exactly why this ADR exists (per AGENTS.md).
  The change is purely additive — a new optional param — so the forward-only contract discipline is
  respected.
- Determinism requirements (metric fixed per `module_version`, deterministic tie-break) keep cache
  keys stable: the same `(image, palette, module_version)` always produces the same output and the
  same cache key. A future metric swap is a `module_version` bump, which correctly invalidates
  cached outputs per ADR 0006.
- The distance computation is O(width × height × palette_size) in the naive form; for large images
  and large palettes this is more expensive than median-cut. Acceptable for the refinement-pass
  use case (run once, on the user's explicit request); vectorizable with numpy if it shows up in a
  profile.
- The default-quantizer upgrade is deliberately not frozen here. If it later proves to need new
  contract surface (e.g. a `method` param exposing the algorithm choice), that would be a separate
  ADR; as described it is implementation-only and needs none.
