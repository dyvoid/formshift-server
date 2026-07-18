# ADR 0021: Colormask grow (trapping)

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

The multicolor pipeline (ADR 0011) traces each color mask independently: `posterize` → one
`image.colormask` per palette index → one `potrace.trace` per mask → `svg.colorize` → binary-tree
`svg.merge`. Because the masks are disjoint and traced separately, adjacent regions can disagree
on their shared boundary — a one-pixel hairline gap in the merged SVG where neither color's trace
covers the seam. This is the classic "trapping" problem from print prepress, surfaced here as
visible seams in multicolor vector output.

The roadmap has tracked this as a Candidate since 2026-07-18, with the fix already identified and
one alternative already rejected:

- **Chosen fix: optional `grow` param on `image.colormask`.** Dilate the binary mask by N pixels
  before output, so each color's trace deliberately overflows its true boundary by a controlled
  amount and overlaps its neighbor. Adjacent grown regions cover the seam; the merge order
  (already pinned per ADR 0014 where it matters) decides which color wins the overlap. Cheap,
  local, per-color, and the user picks N per branch.
- **Rejected: full Inkscape-style stacking / overprints.** Tracing near-the-whole-canvas per layer
  and relying on overprint compositing forces pinned-order rendering *everywhere* (not just where
  overlap is intentional) and discards the per-color independence that makes the parallel executor
  (ADR 0010) and per-leaf caching (ADR 0006) pay off. Rejected 2026-07-18; not reconsidered here.

The fix is a one-line morphological dilation on an already-binary mask. The only question worth an
ADR is the contract shape, because `image.colormask`'s manifest is a frozen contract surface.

## Decision

**Contract (additive to ADR 0011).** `image.colormask` gains an optional `grow` param: a
non-negative integer, default `0`. Validation:

- `grow` must be a non-negative integer (explicit 422 on negative or non-integer, never silent
  acceptance). No upper bound is enforced by the contract — a `grow` larger than the image simply
  floods the mask, which is a degenerate but well-defined result the client can choose to ask for.
  A soft cap may be added later if real usage shows footguns, but is not part of the frozen shape.
- `grow: 0` (or absent) → existing behavior exactly. Existing clients are untouched.

**Semantics.** After the existing index→binary-mask mapping (black = selected index, white =
background), if `grow > 0`, dilate the black region by `grow` pixels before encoding the output
PNG. The output stays an `L`-mode binary PNG (black/white), so `potrace.trace` consumes it
unchanged — the grown mask is just a fatter shape to trace. Dilation is morphological (a square
or cross structuring element of radius `grow`); the exact element shape is implementation detail,
not contract, but must be deterministic per `module_version` so cache keys stay stable (ADR 0006).

The grown region intentionally extends *past* the color's true boundary. When two adjacent colors
both grow, their traces overlap at the seam and the merge order resolves which color paints there.
This is the point: the seam is covered by *something*, not left as a gap. The client controls the
trade-off (grow amount per color, merge order) — the server just provides the dilated mask.

**Cache keys.** ADR 0006 keys on `canonical_params`, so a node with `grow: 2` and a node with
`grow: 0` (or no `grow`) get distinct keys automatically. No cache-key change is needed; the new
param is handled for free, same as ADR 0020's `palette` param.

**Out of scope.** This ADR freezes only the `grow` param on `image.colormask`. It does not add a
symmetric `shrink` param (under-trapping is the bug; over-trapping is a tunable, and a shrink can
be expressed by growing the *neighbors* instead). It does not change `image.posterize`, the merge
order contract (ADR 0014), or the trace module. A future `grow`-on-the-trace-side or
boundary-aware tracing is a separate decision with its own ADR if it lands.

## Consequences

- Multicolor traces get a server-side fix for hairline seams: the client sets `grow` per
  `image.colormask` branch and the merged SVG covers the canvas by construction. No client-side
  gap-filling needed.
- The fix is per-color and local, so the parallel executor (ADR 0010) and per-leaf caching
  (ADR 0006) keep their value — editing one color's `grow` recomputes only that branch's path to
  the merge root, exactly like editing any other per-color param today.
- Grown masks overlap at seams by design. This is correct behavior, not a bug: the merge order
  (pinned where it matters per ADR 0014) decides which color wins the overlap. Clients that render
  in completion order without pinning will see the overlap resolve in completion order — the same
  caveat ADR 0014 already documents for overlapping outputs, not a new one.
- New contract surface on a frozen module manifest is exactly why this ADR exists (per AGENTS.md).
  The change is purely additive — a new optional param defaulting to current behavior — so the
  forward-only contract discipline is respected and no existing client breaks.
- Determinism requirement (fixed structuring element per `module_version`) keeps cache keys
  stable: the same `(image, index, grow, module_version)` always produces the same output and the
  same cache key. A future element-shape swap is a `module_version` bump, which correctly
  invalidates cached outputs per ADR 0006.
- The dilation is O(width × height × grow²) in the naive form (or O(width × height × grow) with a
  separable implementation); for interactive use at typical `grow` values (1–4 px) this is
  negligible. PIL's `ImageFilter.MinFilter` (square) or `ImageFilter.MaxFilter` applied to the
  inverted mask gives a pure-PIL implementation with no new core dependency — consistent with
  core's current dependency profile (PIL only; numpy/scipy/scikit-image are in the design-doc
  definition of core but not yet wired into `pyproject.toml`).
