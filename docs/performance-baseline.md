# Performance baseline (M1)

Recorded 2026-07-08 on target hardware, replacing the voided design-phase figures (design doc,
Open risks). Reproduce with `uv run python scripts/bench_baseline.py` — it spawns a real server
subprocess and drives it over HTTP exactly like a client, so every number includes the full
protocol path (auth, session lookup, payload store, job thread, polling).

- Platform: Windows 11 (10.0.26200), Python 3.12.13
- CPU: Intel64 Family 6 Model 142 (quad-core class laptop CPU)
- potrace 1.16 win64; medians of 7 runs; cold = cache defeated per run

| Measurement | Median |
|---|---|
| trace, small 400×300 (cold) | 44.6 ms |
| trace, large 3000×2250 (cold) | 293.5 ms |
| trace, small (fully cached rerun) | 3.6 ms |
| levels ×1, 3000×2250 (cold) | 135.9 ms |
| levels ×6 chained, 3000×2250 (cold) | 779.1 ms |
| per added node (in-process tier) | 128.6 ms |
| downsample→trace, 3000×2250, full quality (cold) | 288.4 ms |
| downsample→trace, 3000×2250, draft@512 (cold) | 50.8 ms |
| draft speedup | 5.7× |

## Interpretation

- **Interactive budget holds for single-step edits.** A cold trace of a large design is ~300 ms;
  a cached rerun answers in ~4 ms, so parameter changes that only touch the tail of a chain feel
  immediate. Draft mode brings the large-design loop under ~50 ms.
- **Per-edge cost is real and is the codec, not the transport.** ~129 ms per added node on a
  3000×2250 image is dominated by PNG decode + re-encode at each edge: the modules exchange
  `raster/png` payloads, so even the in-process tier pays full codec cost per node. This confirms
  the design doc's transport-tiers warning empirically, with the twist that the logical wire
  format (encoded PNG) is the bottleneck before inter-process serialization ever enters the
  picture. The known answer is a raw-buffer interchange type for co-located modules (the
  `raster/rgba8`-style tier the type registry reserves), negotiated behind the same logical
  contract — scheduled thinking for M2+, do not build it before profiling a real client workload.
- **A six-node full-resolution chain is ~0.8 s cold** — acceptable for a deliberate
  full-quality run, too slow for slider-drag interactivity at full resolution. The intended
  interactive path is draft mode (5.7× here, and it scales with resolution since draft cost is
  bounded by `max_dimension`), plus cache reuse for everything upstream of the edited node.

These are baseline figures for a laptop-class CPU; rerun the script when hardware or the module
set changes materially, and update this file rather than scattering numbers through other docs.
