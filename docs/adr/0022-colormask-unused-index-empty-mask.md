# ADR 0022: Colormask unused index yields an empty mask

- **Status:** Accepted
- **Date:** 2026-07-19

## Context

`image.colormask` (ADR 0011) raised a `ModuleError` when the requested index was not among the
image's used indices:

```
index 26 not present in image (used indices: [0, 1, 2, 12])
```

That guard was written when posterize was median-cut only. Under median cut every PLTE index is
used *by construction* — the palette is derived from the pixels — so an unused index could only
mean a client bug, and failing loudly was right.

ADR 0020 invalidated that premise. An explicit palette is frozen as *the supplied palette, in
supplied order*, and nearest-color mapping guarantees nothing about coverage: a user may legitimately
pin a color that no pixel turns out to be nearest to. Observed in real use with a 17-entry palette on
a photo, where a green pinned for a cat's eyes won zero pixels, and reproduced against a live server
with a 32-entry palette on a 4-color test image.

The client cannot avoid this. It learns the palette by reading the PLTE chunk of posterize's output
(transport decode, not processing). Knowing which indices are *used* requires decoding IDAT and
scanning pixels — precisely what the architecture keeps out of the client. Parsing the used-indices
list out of an error string would work but is not a contract.

So the two contracts disagreed, and the failure surfaced as a whole job failing on a palette the
server itself had just accepted.

## Decision

**An index within `[0, 256)` that no pixel uses is an empty selection, not an error.**
`image.colormask` returns an all-white `L`-mode mask — the well-defined "nothing selected" result —
and the caller's branch completes normally.

- The bounds check stays: an index outside `[0, 256)` is still a `ModuleError`. That is a malformed
  request, not an empty result.
- No other validation is added. In particular, colormask does not check the index against the PLTE
  length; an in-range index beyond the supplied palette is simply unused, which this ADR already
  covers.
- `grow > 0` (ADR 0021) on an empty mask stays all-white — dilation spreads black, and there is
  none — so trapping is unaffected.

Downstream, an all-white mask means `potrace.trace` yields a valid but path-free SVG, `svg.colorize`
no-ops on it, and `svg.merge` merges it harmlessly. This is verified end to end, not assumed
(`tests/test_multicolor_e2e.py`): potrace's tolerance of an all-white input was the one place the
decision could have failed downstream.

## Consequences

- The fan-out contract clients depend on now holds unconditionally: a client that reads N entries
  from the PLTE and builds N branches gets N branches that resolve. That is the real reason this is
  contract surface and not an implementation detail — the guarantee is what makes the client's
  pixel-free palette read sound.
- Documented error behavior on a frozen module is removed, which is why this needs an ADR rather
  than a quiet patch. It is a strict widening: every request that succeeded before still succeeds
  identically. Only requests that previously failed now succeed, so no existing client breaks —
  the same forward-only discipline as ADR 0021's additive param.
- A genuine client bug (asking for an index it never meant to) is now silent, surfacing as an empty
  layer instead of a hard error. Accepted deliberately: the server cannot distinguish that case
  from a legitimately unused palette entry, and under ADR 0020 the legitimate case is the common
  one. An empty layer is visible in the client's own output.
- Cache keys are unaffected (ADR 0006): the same `(image, index, grow, module_version)` still maps
  to the same output. The empty mask is a normal cacheable result.
- ADR 0011's guard is superseded on this one point. The rest of ADR 0011's colormask contract —
  palette-mode input requirement, black-selected/white-background binary `L` output — stands
  unchanged.
