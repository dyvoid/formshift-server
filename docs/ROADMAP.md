# Roadmap

This is the "what might come next" document for the server. It is not a sprint board or a
commitment list. Anyone should be able to scan it without archaeology.

Status values:
- **Candidate** — idea worth tracking; no decision made yet
- **Planned** — decision made, not started; ADR exists or is in progress
- **In flight** — actively being worked on; see [PICKUP.md](../PICKUP.md) for current state
- **Done** — shipped; kept here for a while for context, then archived

Milestones below are defined in the Milestones section of
[Design](architecture/design.md). Each has a testable exit condition, not a date — see that
document for full detail; this table tracks status only. The full server design (contracts,
caching, security, isolation model, etc.) also lives there, not restated here.

| Feature | Status | Description | ADR |
|---|---|---|---|
| M0: Trace (server slice) | Done | HTTP API w/ token auth + sessions, linear DAG executor, hash-chain cache, single potrace module in core env. Exit verified 2026-07-08: PNG → usable SVG entirely over HTTP against the real binary | [0002](adr/0002-http-plus-multiplexed-sse.md)–[0007](adr/0007-jobs-and-sse-events.md) |
| M1: Pipeline (server slice) | Done | Multi-node chains, cache invalidation under reorder (HTTP-level test), draft honored by image.downsample, [performance baseline](performance-baseline.md) recorded 2026-07-08 | [0008](adr/0008-draft-as-client-built-boundary-node.md) |
| Raw-buffer interchange for co-located modules | Candidate | Baseline shows ~129 ms/node PNG codec cost at 3000×2250; a raw-buffer type (reserved `raster/rgba8`) behind the same contract is the known fix. Profile a real client workload first | — |
| Boundary trapping for multicolor traces | Candidate | Disjoint color masks are traced independently, so adjacent regions can disagree on their shared boundary — hairline gaps in the merged SVG. Known fix: optional `grow` param on `image.colormask` (dilate N px before tracing = trapping); full Inkscape-style stacking rejected 2026-07-18 (overprints, forces pinned-order rendering everywhere, traces near-whole-canvas per layer). Additive manifest change → needs an ADR when it lands. Gated on a real client trace where seams are visible | — |
| Non-Vector reference extension (agnosticism stress test) | Candidate | A deliberately non-Vector extension in-tree (e.g. batch image processing, or an audio pipeline exercising a non-`raster/*` type) to falsify the "agnostic engine" claim without waiting for a real second consumer. Purpose is to surface real gaps from a real different workload — gaps so surfaced become legitimate roadmap items; this is the bar the design doc sets for scheduling new contract surface. Not a Vector feature, not M5 (M5 is for real external consumers); a cheap internal probe that breaks the "can't get a second consumer without capability, can't justify capability without a second consumer" circularity | — |
| Split vector modules out of core; move domain extensions to own repos | Planned | `potrace.trace` (a copyleft GPL-2.0 subprocess binary, not classical CV), `svg.merge`, and `svg.colorize` (Vector-shaped SVG operations) currently live in `core/` as a build-sequence artifact from M0, in direct contradiction of the design doc's own definition of Core as "the common classical CV stack (PIL, numpy, scipy, scikit-image)". `default_registry()` in `app.py` hardcodes the full core set with no knob to exclude them. Decision (ADR 0016 + ADR 0017, Accepted 2026-07-18): these modules move into a separate extension in its own repo; the existing in-tree `extensions/background-removal/` also moves to its own repo; core becomes strictly classical CV; `default_registry()` becomes configurable. Domain extensions live in their own repos, not in-tree — the ComfyUI-custom-nodes model, with per-extension venv isolation on top. The decisions are final; implementation is in-flight work, not gated on a future consumer. See Open risks in [Design](architecture/design.md) for the original rationale | [0016](adr/0016-vector-modules-out-of-core.md), [0017](adr/0017-extensions-live-in-own-repos.md) |
| Git-URL extension install | Planned | `POST /v1/extensions` currently accepts only `{"path": "<local dir>"}`. Under ADR 0017 (extensions live in own repos), the canonical home of an extension is a git URL, but the install API can't install from one — the client must clone first. Decision (ADR 0018, Accepted 2026-07-18): add a `{"git": "<url>", "ref": "<optional>"}` form; server clones to a temp dir and runs the existing install path. `path` and `git` mutually exclusive. Public repos only in the first cut; private-repo auth is a follow-up. New contract surface on a frozen API — ADR freezes the field shape deliberately | [0018](adr/0018-git-url-extension-install.md) |
| Auto-scan extension source dir on boot | Planned | Dev workflow today requires `POST /v1/extensions` once per extension before it auto-loads, even for local checkouts. Decision (ADR 0019, Accepted 2026-07-18): a separate `--extensions-source-dir` CLI flag (distinct from `--extensions-dir`) that the server scans on boot, auto-installing any subdir with an `extension.toml`. Reinstall triggered by version bump in the manifest. Off by default; loud failure on bad manifests. Pairs with ADR 0018 (clone several repos into a source dir, point the flag at it, boot). Dev affordance, not a production path — production installs via the API into `--extensions-dir` and uses `load_installed()` | [0019](adr/0019-auto-scan-extension-source-dir.md) |
| M2: Color (server slice) | Done | Multi-input merges w/ order-aware cache keys (`svg.merge`), parallelized per-color tracing on the thread-pool executor, progressive streaming (disjoint path) exercised by a 16-color trace. [Parallel speedup benchmark](performance-parallel.md) recorded 2026-07-08 | [0009](adr/0009-fixed-arity-ports.md)–[0011](adr/0011-color-separation-modules.md) |
| M3: Extensions (server slice) | Done | Isolated-venv extension installation (`/v1/extensions`, per-extension venv + stdio runner), first out-of-core extension (background removal, rembg). Exit verified 2026-07-09: an extension pinning Pillow below core's version installs into isolation over HTTP and works | [0012](adr/0012-isolated-extension-venvs.md)–[0013](adr/0013-extensions-api.md) |
| M4: Print (server slice) | Done | Pinned-order progressive path: output groups (`outputs[].group` + `groups[].order`) hold overlapping outputs so they stream in declared order. Exit verified 2026-07-09 by test: first-declared output completes last yet emits first | [0014](adr/0014-pinned-order-output-groups.md) |
| M5: Open house | Candidate | LAN binding opt-in w/ enforced token, workspace grouping w/ install-time dependency resolution, cache eviction policy, module-author docs, standalone release. Gated on a non-Vector consumer existing | — |

Note: milestones are one track shared with the Vector client repo — each server capability above
ships alongside the Vector feature that consumes it (per the Design doc), except M5, which
is explicitly for other consumers. Vector-side work is tracked in the Vector repo, not here.

---

## Archive

_Nothing archived yet._
