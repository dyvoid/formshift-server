# Parallel tracing speedup (M2)

Recorded 2026-07-08 on target hardware, closing the M2 open risk that parallelized per-color tracing
might not speed up on real multi-core hardware. Reproduce with
`uv run python scripts/bench_parallel.py` — it spawns a real server subprocess and drives it over
HTTP, so every number includes the full protocol path.

- Platform: Windows 11 (10.0.26200), Python 3.12.13
- CPU: Intel64 Family 6 Model 142 (8 logical processors)
- potrace 1.16 win64; medians of 5 runs; cold = cache defeated per run
- Workload: 1600×1600 synthetic 16-color design → `image.posterize` → 16 × (`image.colormask` →
  `potrace.trace` → `svg.colorize`) → binary `svg.merge` tree

| Configuration | Median |
|---|---|
| workers=1 (sequential) | 1828 ms |
| workers=default (8) | 747 ms |
| speedup | 2.45× |

## Interpretation

- **Independent branches do scale on this hardware.** A 2.45× speedup on 8 logical cores for a
  16-branch workload confirms the parallel executor is effective, even though the workload includes
  serial merge stages and per-node HTTP/polling overhead.
- **The speedup is sub-linear**, which is expected: the workload has a serial posterize at the start,
  a serial merge tree at the end, and each branch itself contains sequential mask→trace→colorize
  nodes. Not all 16 branches are ready at the same instant, and some cores sit idle during the
  final merges.
- **The dominant cost is still per-node PNG codec and potrace**, not scheduling. This is consistent
  with the M1 baseline finding that in-process raster edges are expensive because every edge is a
  full PNG decode/encode. The raw-buffer interchange candidate remains the structural fix if a real
  client workload needs more.

These are M2 exit figures for this laptop-class CPU; rerun the script when hardware or the module
set changes materially, and update this file rather than scattering numbers through other docs.
