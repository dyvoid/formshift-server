# Formshift Server & Formshift: Vector

**Formshift Server**: a module execution engine. A standalone process exposing an HTTP API, built around a DAG of typed processing units with per-node caching, progressive results, and network-transparent execution. Its contract is open on three axes (data types, module implementation language, clients) and deliberately opinionated on a fourth: it executes one-shot, cached, interactive pipelines, and nothing else. See "What this engine is and is not."

**Formshift: Vector**: a non-destructive raster-to-vector tracing app for print and general design work. The first client built on Formshift Server.

Two separate repos, two separate names. The server doesn't know what a vectorizer is, runs fine on its own, and has no dependency on any particular client or packaging. Vector is one app that embeds it.

---

## Part 1: Formshift Server

### Deployment model

The server is an ordinary standalone process: install it, run it, get an HTTP API on a port. No assumptions anywhere in the codebase that a parent process launched it, that a client lives on the same machine, or that any particular UI exists. Standard daemon hygiene from day one:

- Clean shutdown on SIGTERM.
- `--port` flag with `--port 0` support (OS picks a free port, server reports the chosen port on stdout), so a host app can spawn instances without conflicts and a standalone user can pin one.
- A `/health` endpoint.
- Logs to stdout or file, no client-specific channels.
- Auth token accepted via flag, environment variable, or config file; connection info printed on startup.

Standalone mode doubles as the development and test mode: the server is built and tested against curl and a plain test suite, with no GUI in the loop. That keeps the client-independence claim honest, because the project is its own first external client.

Embedding the server inside an end-user app (bundled interpreter, process spawning, port capture) is entirely the embedding app's concern. See Part 2 for how Vector does it.

### Why build this instead of using something that exists

Seven candidate categories were checked directly against the requirements (typed heterogeneous I/O, per-node caching, sub-second interactive latency, permissive licensing, lightweight footprint, extensible without recompiling):

| Candidate | Domain it comes from | Why it doesn't fit |
|---|---|---|
| ComfyUI | Generative AI models | GPL-3.0 license, gigabytes of PyTorch/CUDA dependencies, tensor-only I/O types; its own maintainers have an open unresolved issue acknowledging it doesn't package into a lightweight standalone runtime |
| GEGL | Photo editing (GIMP's core engine) | Graph edges are hardcoded to raster buffers only (`GeglBuffer`), no path for heterogeneous output types; C-native |
| OpenFX | VFX compositing (Nuke, Resolve/Fusion) | Best-licensed (BSD) and philosophically closest (a real standard for host-independent pluggable processing units), but raster/frame-only, and plugin authoring is C++ against a spec, a much higher bar than a documented HTTP contract |
| Node-RED | IoT / home automation | Confirmed from its own docs: a node can have at most one input port, ruling out multi-input merges; execution model is message-passing between always-running nodes, not deterministic cached compute |
| Workflow orchestrators (Dagster, Prefect, Snakemake, Ray) | Batch data pipelines | The closest match on paper (typed DAGs, memoization), but built for batch jobs: per-task overhead in the tens to hundreds of milliseconds plus scheduling and logging infrastructure, designed for tasks measured in minutes, not an interactive loop measured in tens of milliseconds |
| Graphite (Graphene engine) | 2D graphics editing | The only candidate whose graph genuinely carries heterogeneous data types (raster and vector together), Apache 2.0, actively developed. But it is an editor, not an embeddable engine: processing units are compiled-in Rust, there is no out-of-process module protocol, no bring-your-own-dependency path (Python ML models can't drop in), and no headless client-independent API |
| FBP Network Protocol (NoFlo ecosystem) | Flow-based programming | A real standardized protocol (schemas, test suite, secret-based auth) for graph runtimes driven by interchangeable clients, the closest thing to prior art for this project's protocol layer. Not adoptable: WebSocket message-passing with FBP packet semantics rather than deterministic cached compute, and the ecosystem has been essentially dormant since roughly 2018. Its component manifest spec (fbp-manifest, including an `exec` field for standalone-process components) is worth reviewing before this project's manifest format is frozen |

The pattern: each was built by an industry that needed part of this, and each baked in assumptions that conflict with the rest. What none of them offers is the combination itself: an embeddable, client-independent engine whose modules are out-of-process, bring their own dependencies in any language, and can carry heterogeneous data types (raster pixels becoming vector path data mid-pipeline) over one documented protocol.

### What this engine is and is not

The engine's openness is real on three axes and deliberately absent on a fourth. Open: data types flowing through the graph (open namespace, see Modules), module internals (any language, any dependencies, out-of-process), and clients (any frontend speaking the protocol). Opinionated: the execution model. This engine runs **one-shot, cached, interactive pipelines**: a job executes each module to completion, materializes and caches whole outputs, and streams results as they finish. That execution model is a genuine commitment, not a temporary limitation, and there is strong evidence the commitment is correct: no execution-model-neutral engine exists anywhere. GStreamer (streaming), Bazel (builds), Ray (distributed batch) each picked one model and became excellent within it.

**Reference workload.** The contract is workload-neutral; the performance engineering is not, and pretending otherwise would be dishonest. Engineering decisions (transport tiers, cache sizing, interactivity budgets) are driven by a named reference workload: interactive image-pipeline editing, currently Formshift: Vector. Workload classes the reference never exercised may impose requirements this engine has not been built for, and those get engineered when a real consumer brings them, per the build strategy below.

**What still fits the one-shot model**, for calibration: generative ML pipelines (diffusion image or music generation) fit as long-running coarse modules with progress events. Coarse is a real constraint, not a style choice: out-of-process modules cannot share GPU memory, so a diffusion pipeline is one fat module owning its own model residency, not a chain of fine-grained GPU stages passing latents. Batch media processing (whole file in, whole file out) also fits.

**Non-goals**, stated so nobody, including this project's own future, mistakes the scope:
- Streaming or timeline-scrubbing media editing. Frame-level streaming semantics, backpressure, and chunked temporal caching are a different execution model (GStreamer's, roughly two decades of engineering).
- Realtime processing (live audio, live video). A third execution model with hard latency guarantees this engine does not make.
- Cross-module GPU memory residency. Keeping multi-gigabyte model weights hot across module boundaries requires a shared-process VRAM broker, which contradicts the out-of-process isolation this design is built on.
- A job scheduler. There is currently no queue or contention model; the engine assumes near-immediate execution. Adequate for interactive image work, a known gap for concurrent long GPU jobs, and listed in open risks.

### Modules

A **module** is a processing unit defined purely by its I/O contract. Internals are a black box: the server cares only about what types a module accepts and produces and that it speaks the protocol. A module can be written in any language and bring any dependencies, since the contract is HTTP in and out.

**Port types are an open namespace with strict matching.** Types are strings a module declares, not a fixed enum, so new domains (vector paths, meshes, audio, anything) need no engine changes. Connections are strictly type-checked at connection time; openness in the namespace does not mean anything connects to anything. This validation lives in the server, at the protocol level, so every client gets it, not just the one that implemented a check in its UI.

**A type string implies a wire format.** Two modules both declaring "image" but meaning different encodings (PNG bytes vs. a raw RGBA array) would type-check and then crash at runtime. Type names therefore carry their encoding by convention, e.g. `raster/png`, `raster/rgba8`, `vector/svg`, maintained in a small registry document. First-party extensions establish the conventions; third-party modules reuse existing type strings to interoperate or mint new ones for new data kinds.

### Execution model: DAG

The engine executes a directed acyclic graph of module instances and typed connections, not a fixed linear chain, even when a client only ever presents a linear stack. Precedent says this is well-trodden: GEGL, GIMP's core engine since 2.10, is a DAG with lazy on-demand evaluation and the same fast-preview/full-quality split described below.

Building for a graph from day one costs little over building for a line: named typed ports instead of one implicit input, connections as an explicit edge list, topological sort instead of a for-loop. Retrofitting graph support into code that assumed linear execution is the expensive path.

Multi-input modules (merges, blends) need input-order-aware cache keys, since combining inputs is not generally commutative: blend(A, B) is not blend(B, A).

### Caching

Every module instance's output is cached, keyed on a hash chain: the instance's own parameters plus the hash of its upstream inputs. Editing or reordering one instance reruns only what is actually downstream of the change.

Two open design points, flagged rather than resolved here:
- **Recipe-hash vs. content-hash keys.** Hashing the recipe (chain of parameter hashes) is cheapest. Hashing actual output content additionally enables early cutoff: when a parameter change happens to produce identical output, nothing downstream recomputes. Content hashing large buffers is affordable (modern non-cryptographic hashes run at GB/s), but the choice affects behavior with nondeterministic modules (ML inference) and should be made deliberately.
- **Memory budget and eviction.** A 3000×3000 RGBA buffer is roughly 34MB; a ten-layer stack with cached intermediates is hundreds of MB per session before history is counted. The cache needs a budget and an eviction policy (GEGL solved this same problem with tile caching and disk swap). Unbounded caching is not a viable default.

### API

The server exposes a local HTTP API plus one push channel:

- **HTTP** for discrete request/response operations. Stateless, debuggable with curl and browser devtools.
- **SSE (Server-Sent Events)** for progress during long-running jobs: one-directional server-to-client push, which is exactly what SSE is for. Honest divergence note: the peers in this space (ComfyUI, Jupyter, the FBP protocol) all chose WebSocket. SSE is kept because the push is genuinely one-directional; commands travel the other way as plain HTTP, including cancellation, which is a first-class endpoint (a DELETE on the job) rather than a future maybe, since any module that runs for minutes makes cancel a day-one need.
- **One multiplexed SSE channel per client, not one per job.** Browsers (including Electron's Chromium renderer) cap HTTP/1.1 connections at six per origin; a channel per running job exhausts that immediately on a busy graph. Job progress events are multiplexed over a single stream with job IDs.

Transport rules baked in from the start, each cheap now and expensive to retrofit:
- **Payloads travel over the API as binary bodies (raw or multipart), never base64-in-JSON, and never as shared filesystem paths.** Path-passing silently breaks the moment client and server are different machines.
- **Upload once, reference by ID.** Source data is uploaded to a session and subsequently referenced by identifier; interactive parameter changes never re-send the source.
- **Explicit session/project IDs on every request, no implicit global state.**

**Transport tiers.** The logical contract (typed payloads between modules) is one thing; the physical channel is another, and conflating them would repeat a mistake every in-process peer avoided. ComfyUI, chaiNNer, and GEGL all pass buffers by reference inside one process at zero per-edge cost. A naive reading of "modules speak HTTP" would instead serialize every intermediate buffer at every graph edge, and for full-resolution raster buffers that per-edge cost could rival module compute itself, eroding the interactivity the whole design protects. The commonly accepted answer, with media pipelines like GStreamer as the canonical precedent, is transport negotiation behind one unchanged logical contract:
1. Modules in the core environment dispatch in-process: a function call, zero copies.
2. Local out-of-process modules exchange shared-memory handles; the protocol message carries a buffer reference, not the bytes.
3. Only genuinely remote modules fall back to bytes over the wire.
The contract is identical in all three cases; only the payload channel varies, negotiated by co-location.

### Security

**Token auth is on by default, including for pure localhost use.** This is a deliberate reversal of the intuition that localhost is private. The 2024 "0.0.0.0 Day" research (Oligo Security) demonstrated drive-by browser attacks achieving remote code execution against local, unauthenticated HTTP services, with Ray, Selenium Grid, and PyTorch TorchServe as proven targets: any webpage open in any browser can fire requests at localhost ports. Browsers have since blocked the specific 0.0.0.0 vector, but the class (CSRF against local services, DNS rebinding) remains, and the mitigations recommended by that research are exactly: require authorization even locally, and validate Host/Origin headers.

Formshift Server is a worse-than-average target for this class, because its purpose is executing modules and its extension installer downloads and runs code. The design follows the canonical precedent for exactly this situation: Jupyter, a localhost code-execution server, has shipped token auth enabled by default for years (token generated at startup, printed to the terminal for copy-paste, disabling documented as "NOT RECOMMENDED"). So:
- The server requires a bearer token on every request. It generates one on startup if not provided, and prints it with the connection info. An embedding app captures it; a standalone user copies it.
- Host and Origin headers are validated against an allowlist (default: localhost forms only).
- Binding defaults to `127.0.0.1`. Binding to a LAN interface is an explicit opt-in flag, and doing so without a configured token is a startup error, not a warning.

### Draft and quality modes

Default is full-quality preview, not draft. During this project's own development, a broken vectorization pass looked completely fine as a small thumbnail and was only caught by pixel-level comparison at full resolution; defaulting to draft would build that failure mode into every user's workflow.

Draft is a global toggle: enabling it puts every module in the graph into draft mode, no per-module override. A module that implements nothing special for draft simply runs at full cost. Draft is an opt-in speedup, never a silent quality downgrade a module author forgot to handle. Draft applies to both preview and export, since some workflows legitimately want the faster result as output.

The server owns only the draft flag; what draft means is the pipeline's decision, because it is workload-specific. For the raster reference workload, the strategy is downsampling once at the pipeline boundary, so every module processes fewer pixels for free without being resolution-aware. Other workloads would define draft differently (fewer inference steps for a generative module, lower sample rate for audio); there is no universal downsample. Modules implement custom draft logic only when they want something smarter than the pipeline-level default, such as substituting a cheaper algorithm.

### Progressive rendering

Results stream to the client as individual module outputs complete rather than waiting for the whole graph. This is safe when outputs are disjoint: non-overlapping regions cannot display incorrectly regardless of completion order. It is not safe when outputs deliberately overlap by design (a white underbase layer beneath other ink colors, for example); those need a pinned render order or the user sees a wrong composite while later results are still arriving. Two code paths, decided per output group, not one implementation assumed to generalize.

### Extensions and dependency isolation

The server ships with nothing installed. Modules are grouped into extensions (an installable package bundling related modules), and extensions declare their own dependencies.

**Isolation model, three tiers:**
1. **Core**: one shared environment for the common classical CV stack (PIL, numpy, scipy, scikit-image). Architecturally just an extension like any other, with no special-cased path in the engine; clients typically bundle and enable it by default as a packaging choice, which is a different fact from being structurally privileged.
2. **Everything else defaults to its own isolated venv**, running as its own process with its own dependencies and model weights, spun up on demand, speaking the same HTTP contract. The engine is blind to what's inside.
3. **Workspace-level grouping**: a client app can define a workspace config declaring which extensions share an environment and which stay self-contained. The installer must resolve the combined dependency set of a proposed shared group before committing, catching conflicts at install time instead of runtime. An extension's manifest can force isolation, overriding any grouping, for authors who know their dependency set is fragile.

The isolation model responds to a documented, current failure mode, not a hypothetical. rembg has a live GitHub issue showing the NumPy 2.0 breaking-change error, and Arch Linux packagers independently recommend running it in an isolated venv for the same reason. A January 2026 ComfyUI extension bug report shows a cascade of simultaneous conflicts (one package requiring `numpy>=2.1`, another rejecting `numpy>=2.0`, mismatched `pillow`, rejected `torch`) from forcing ML-adjacent packages into one shared environment. ComfyUI's own documentation confirms it installs all custom-node dependencies into a single shared environment, and separately admits: "dependency conflicts are a common issue... after installing or updating a custom node, previously installed custom nodes can no longer be found."

Honest divergence note: no peer application does tiered isolation. Even chaiNNer, which got embedded Python and manifest-declared dependencies right, still installs everything into one integrated environment (its own release notes instruct users to reinstall all dependencies after a Python update). The tiered model diverges from every peer deliberately, on the evidence above; the closest precedent is not in this app category but in the broader Python tooling world, where per-application isolation (the pipx and uv-tool model) is established practice. It should still be said plainly: this exact three-tier design has no production miles on it anywhere.

---

## Part 2: Formshift: Vector

### Problem

Open source raster-to-vector tooling is a black box: image in, SVG out, with at most a handful of trace-time parameters. But output quality is mostly decided outside the trace step. Preprocessing (cleanup, background removal, levels, thresholding) determines what the tracer sees; post-processing (path cleanup, simplification, color separation) determines whether the result is usable. Interactive control over both sides, with a live view of the result, is essential for a good vector, and no open source app offers it as one pipeline. One illustration: threshold and cleanup choices before tracing decide which fine detail survives at all, and single-shot tools make that choice invisibly, discoverable only by inspecting the output afterward.

Nearest existing things, checked directly (mid-2026):

- **Inkscape's Trace Bitmap**: a modal dialog with trace-time options. Preprocessing means round-tripping through a separate raster editor; post-processing is manual path editing.
- **ComfyUI with community ToSVG nodes** (vtracer and potrace variants): the closest working thing. Real preprocessing plus trace in one cached graph, and a few post nodes (path simplify, quantize). Falls short as a product for this job: queue-and-rerun interaction rather than live parametric preview, essentially no vector-side post-processing beyond simplify, and a gigabyte-class PyTorch stack plus GPL-3.0 attached to what is fundamentally a diffusion tool.
- **Graphite**: the closest in spirit. Non-destructive layer/node hybrid over raster and vector, Apache 2.0, desktop builds in release candidate. Has no bitmap tracing at all today, raster support is explicitly experimental, and its processing units are compiled-in Rust with no out-of-process module protocol and no path for external dependencies like Python ML models. Contributing a trace node there would yield a trace inside one editor, not a reusable engine, an ML-capable module ecosystem, or print finishing.
- **Commercial tools** (Vectorizer.ai, Illustrator's Image Trace) produce good results but are closed and expose little to no pre/post control.

Separately, no general-purpose vectorizer serves print production's downstream needs: spot-color separation, underbase generation for dark garments, trapping against press misregistration. Dedicated separation software exists but doesn't trace; tracers don't separate. Vector spans both.

### Scope

Any arbitrary image in, best possible vector out, where "best possible vector" means the best achievable flat vector-art aesthetic, not photorealistic reproduction. Deliberate scope decision.

Photographic and gradient content is in scope as input, but output is always a flat, posterized, vector-styled result (the "poster" look). This removes any need for an ML photo-vectorization backend (gradient mesh fitting, differentiable rendering): posterizing a photo into flat tones and tracing each tone is a well-established technique on the same potrace pipeline used for line art. If a future version needs photorealistic vector output, that is a different product with a different core algorithm, not an extension of this one.

### Pipeline architecture

Two data phases with a hard boundary, expressed as a graph on Formshift Server:

1. **Raster stack**: modules operating on pixel buffers. Crop, rotate, levels, threshold, background removal, sketch/line-art extraction, super-resolution, smart region selection. Freely reorderable; classical CV and AI modules mix freely since both map pixel buffer to pixel buffer.
2. **Binarize**: the one-way door. Continuous pixel values become a binary mask. Pinned near the end of the raster stack because nothing downstream of it can see color or gray-level information again; free reordering across this boundary produces invalid pipelines (binarizing before background removal destroys the color data removal needs), a lesson taken from darktable's pixelpipe, which fixes execution order for correctness while presenting an editable history.
3. **Potrace**: the trace step, a module like any other to the server. Fed raw grayscale with potrace's native blacklevel parameter (`-k`) exposed as a live "detail recovery" dial. Mkbitmap-style high-pass pre-filtering is deliberately avoided: it is tuned for OCR document cleanup, and on a development test case it visibly destroyed thin organic linework, consistent with that documented purpose. Potrace's core is monochrome-only, confirmed against the maintainer's own statements. Multi-color output is built on top: posterize to N flat colors, one binary mask per color, one potrace run per mask, merge paths with fills. Mature pattern (Inkscape's color trace, `node-potrace`'s Posterizer, coltrace).
4. **Vector stack**: modules operating on path data. Corner smoothing, curve simplification, spot-color separation, underbase generation, trapping, stroke width adjustment.

### Licensing note on potrace

Potrace is GPL-2.0. Vector invokes it strictly as a subprocess, data over pipes and files, which is aggregation, not linking, and does not affect the licensing of Vector's own code. This boundary is deliberate and must be preserved: switching to a linked binding (pypotrace or similar) as an "optimization" would silently change the project's licensing situation. Distributing the potrace binary alongside the app requires complying with GPL source-availability terms for that binary, which is routine.

### Terminology

- **Module**: a processing unit defined by its I/O type contract (server concept).
- **Layer**: a module instance placed in a project's stack. Module is the type, layer is the placement; Vector's linear stack is a degenerate case of the server's graph.
- **Layer UI**: the control panel for one layer's interactive components.

### Color handling and performance

Per-color tracing scales roughly linearly with color count: one independent potrace call per color. That structure, not any specific measurement, is the design input; all performance figures gathered during design exploration came from an unrepresentative environment and are treated as void until the M1 baseline exists.

Color count is not capped to solve the scaling. Real separation tools (InkSplit, Separation Studio) routinely output 10-16+ ink channels for simulated process work; a cap would amputate that use case. Instead:
- **Parallelize the per-color calls.** Each color's trace shares no state with any other: embarrassingly parallel by structure. Actual speedup on target hardware is unmeasured and is an explicit M2 exit condition.
- **Decouple preview resolution from export resolution**, per darktable's precedent.
- A soft cap on live-preview color count remains available as a low-end-hardware safety valve; a UX detail, not a product limit.

### Preview interaction and throttling

Any control that streams intermediate values during one interaction (sliders, color-wheel drags, crop/rotate handles, drag-to-reorder, held steppers) gets two independent adjustable behaviors: a throttle/debounce rate, and a commit-only option (fire on mouse-up/enter only). Discrete controls (checkboxes, dropdowns) have no stream to throttle.

Throttling alone doesn't make fast interaction correct. Multiple in-flight async requests can resolve out of order, flashing a stale result over a newer one. The client tracks the latest request per control and discards or cancels superseded responses; throttling reduces the frequency of the race, tracking eliminates it.

This is a separate axis from draft mode: draft is how expensively a module computes when asked, throttling is how often it gets asked.

Module-internal throttling exists beneath UI throttling and is not redundant with it. Modules can be driven by any client or by direct API calls, not only by one particular frontend; UI throttling is a courtesy of one particular frontend, module-internal throttling is the only limit that holds for all callers.

### Layer controls

Every layer has an on/off toggle, no exceptions.

Blend mode and opacity are granted by a structural rule, not a per-type whitelist: any layer whose output preserves pixel-coordinate correspondence with its input (same canvas dimensions, (x,y) in means (x,y) out; true of levels, HSL, threshold, background-removal strength) gets blend and opacity, because blending against the layer below is well-defined at matching coordinates. Layers that change canvas geometry (crop, arbitrary rotation, resize) don't get the option; there is no coherent blend target across mismatched coordinate spaces.

Deferred, not current scope: a paintable per-layer mask, the natural third control alongside blend and opacity (the pattern of Affinity Photo's Live Filter Layers), enabling regional rather than global application of an adjustment.

### Packaging and tech stack

- **UI shell**: web frontend (canvas interaction library, Fabric.js or Konva) wrapped in a native container (Electron or similar). Presentation and interaction only; all processing routes through Formshift Server's API. The Electron choice is Vector's alone and implies nothing about the server.
- **Embedded runtime**: Vector bundles its own Python interpreter and the Formshift Server package inside the installer, spawns the server on launch, captures the port and auth token, and shuts it down on exit. End users never see Python. Real forum evidence shows ordinary users fighting pip, PATH, and interpreter-version issues just to run a single background-removal script; both ComfyUI's portable distribution and chaiNNer (which downloads an isolated Python build on first start for exactly this reason) demonstrate the pattern works.
- **Desktop-first, by deliberate choice**, for a stack of practical reasons rather than any single one: no hosting to run or pay for; a portable build can be handed to a non-technical person and just opened, with no separate server process and browser tab to orchestrate; native local file handling (open, save, watch folders) instead of upload/download round trips; everything works offline; no per-interaction network latency; and local AI modules (background removal, segmentation) run as ordinary processes with full hardware access instead of fighting a browser sandbox. A browser deployment stays structurally possible later, the server plus a web client is the same architecture, but it is a possibility deliberately left unexercised, not a target.

### Feature ideas by category

**Raster preprocessing layers**
- Crop, rotate, levels/curves, threshold: standard classical ops from the server's core extension
- Background removal (U²-Net/rembg-class model, ~1M params, CPU-viable)
- Photo/render-to-line-art extraction, for sources that aren't line art yet, a genuinely separate input class
- Smart region selection (MobileSAM-class model) for manually correcting ambiguous thin-line regions
- Super-resolution pre-upscale for low-resolution source logos (risk: hallucinated detail; fine for casual reuse, wrong where geometric fidelity matters)
- Vesselness/ridge filtering as a conservative detail-recovery mode, measured competitive with more aggressive methods specifically at the low-recovery end of the recovery/fattening curve

**Vectorization core**
- Potrace integration with blacklevel as a live parameter
- Live diff overlay against the source raster (pixel-level IoU, gray-band recovery percentage) as a first-class UI element, so trace fidelity is measured in the app instead of eyeballed in an external editor

**Print-specific post-processing**
- Underbase / highlight-white auto-generation for dark garments (overlapping layer: pinned render order)
- Trapping / choke controls against press misregistration (same render-order constraint)
- Live garment-color mockup preview
- Spot-color palette reduction and per-color layer export

---

## Build strategy

Two products that depend on each other invite two opposite failure modes. Building the generic engine to completion before its first app exists produces infrastructure with no validating consumer (the fate of more than one node-tool project). Building both minimally at the same time produces the other classic loss: 80% of the effort going into refactoring, redesign, and architecture churn as the two halves fight each other.

The path between them: **development is linear in contracts, not in code volume.** Everything splits into two categories with opposite rules.

**Contracts: final shape from day one, evolved additively only.** The HTTP protocol, the module I/O manifest, type strings and wire formats, session semantics, auth, the graph data model. These are cheap to design fully (this document is most of that design) and expensive to change once anything depends on them. Forward-only evolution is a designed-in property, not a discipline to white-knuckle: the protocol is versioned, unknown fields are ignored rather than rejected, and new capabilities are opt-in additions. This is the same recipe that let HTTP, protobuf, and LSP evolve for decades without breaking consumers.

**Implementations behind those contracts: minimal, stubbed, filled in linearly.** Filling a stub is forward motion. Internal rework behind a stable contract is discovery, not regression. Concretely:

- The executor walks a DAG topologically from day one; with one node in the graph that is a for-loop in structure, at near-zero extra cost, and multi-node graphs later are just data.
- The module manifest format is complete, including the isolation field, but the only implemented isolation value at first is "core"; anything else returns an explicit not-implemented error rather than being silently accepted.
- The draft flag is plumbed through the protocol; while no module implements it, draft requests simply run at full cost, which is the defined behavior anyway.
- The cache is keyed by the hash chain from day one, even while chains are two links long.

**"Never move backwards" means: never break a shipped contract.** It does not mean never rewrite code. Judging linearity by contract stability while letting internals churn freely avoids the trap of gold-plating implementations up front.

**Freeze the minimum surface, not the maximum.** Every committed endpoint and field is a forever promise, so the frozen protocol is only the part the current version actually touches. The rest of this document is design intent: stable in direction, explicitly unstable in detail until its first real consumer exists. Each frozen contract gets an architecture decision record; anything without one is fair game to change.

### Version 1 scope

Vector v1 does one thing: drop an image in, trace it with potrace, adjust basic controls, export the SVG. That is already a useful tool and the smallest thing that validates the whole stack end to end.

The server slice v1 requires: the HTTP API with token auth and sessions, the trivially-linear DAG executor, the hash-chain cache, and a single module (potrace) living in the core environment. The Vector slice: image drop, live trace parameters with per-control throttling, commit-only mode, and stale-response discarding, an SVG preview, and export. Everything else in this document, multi-module graphs, extension isolation, color separation, print finishing, arrives as later iterations against contracts that already anticipated it.

### Milestones

One track, not two: each server capability lands in the same milestone as the Vector feature that consumes it. No server capability ships unconsumed, except the explicitly-for-others final milestone. Each milestone has a testable exit condition, not a date.

**M0: Trace** (the Version 1 scope above). Server: frozen v1 contract (HTTP, token auth, sessions, multiplexed SSE, manifest format, type strings), linear DAG executor, hash-chain cache, potrace module in core. Vector: image drop, live trace parameters with throttling, commit-only mode, stale-response discarding, SVG preview, export. Dev-mode launch suffices; no installer yet.
Exit: take a real design from PNG to production-ready SVG using only the app.

**M1: Pipeline.** Server: multi-node chains, cache invalidation under reorder, draft flag honored by at least one module. Vector: the layer stack UI (crop, rotate, levels, threshold), binarize pinned late, per-layer on/off, blend/opacity per the structural rule, A/B compare, packaged installer with embedded Python.
Exit: reordering a mid-stack layer recomputes only downstream; the installer runs on a clean machine; and a performance baseline (trace time, per-edge transport cost, cache hit behavior) is recorded on target hardware, replacing the voided design-phase figures before any performance tuning happens.

**M2: Color.** Server: multi-input merges with order-aware cache keys, parallelized per-color tracing, progressive streaming (disjoint path). Vector: posterized multi-color tracing, progressive layer rendering, draft toggle, diff overlay (pixel IoU, recovery metrics) as a first-class UI element.
Exit: a 16-color trace renders progressively, and the parallel tracing speedup is benchmarked on real multi-core hardware, closing that open risk.

**M3: Extensions.** Server: isolated venv installation implemented (not-implemented stubs replaced), first out-of-core extension: background removal (rembg-class). Vector: background-removal layer; the extension-discovery UX decision is forced here rather than left open.
Exit: the extension installs into isolation on a machine where its dependency pins would conflict with core, and works.

**M4: Print.** Server: pinned-order progressive path for overlapping outputs. Vector: vector post-stack (simplify, corner smoothing), spot-color separation, underbase generation, trapping, garment mockup preview.
Exit: produce separations for a real print job fit to hand to a printer.

**M5: Open house.** Server only: LAN binding opt-in with enforced token, workspace grouping with install-time dependency resolution, cache eviction policy, module-author documentation, standalone release. Gated on an external-style consumer existing, even if that is a second internal client.
Exit: something that is not Vector drives the server end to end.

Sequencing notes: M0 through M2 are dependency-ordered. M3 and M4 can swap depending on which matters first to real work. The installer sits in M1 rather than M0 deliberately (M0 serves its own developer; packaging should not delay first real use), and the diff overlay sits in M2 where multi-color output makes fidelity hardest to eyeball.

---

## Open risks

- All performance figures from the design phase were gathered in an unrepresentative environment (a virtualized single-core sandbox) and have been removed from this document as unreliable. Design decisions justified by performance reasoning (transport tiers, parallel tracing, interactivity budgets) rest on structural arguments until the M1 hardware baseline exists; if that baseline contradicts a structural assumption, the design gets revisited, not defended.
- The shared-memory transport tier is designed but unproven: cross-platform shared-memory lifecycle (especially cleanup after a module crash, and Windows vs. Unix semantics) is known-fiddly systems work, and skipping the tier entirely would put full per-edge serialization on the interactive path.
- There is no job scheduler or queue concept. Acceptable for the interactive reference workload; a real gap the moment concurrent long-running GPU modules exist.
- Cache invalidation across a reorderable graph needs the hash-chain design from the start; retrofitting it is the expensive path. The recipe-hash vs. content-hash choice and the cache memory budget/eviction policy are unresolved design points.
- Enforcing or softly discouraging invalid raster-stack orderings without frustrating users who want real flexibility is an unresolved UX question.
- Bundling a Python runtime inside a native app shell adds real packaging complexity versus a pure-JS stack.
- Parallelized per-color tracing is unbenchmarked on real multi-core hardware; process-spawn overhead at higher concurrency could eat into the projected speedup. Scheduled to close at M2.
- Progressive rendering requires two code paths (completion-order for disjoint outputs, pinned-order for overlapping ones); building only the disjoint case and assuming it generalizes produces visibly wrong output.
- LAN binding is opt-in and refuses to start without a token, but the broader LAN story (certificate/transport security, token distribution across machines) is undesigned.
- Workspace-level shared/isolated extension grouping is only trustworthy with real install-time dependency resolution, not just declared groupings.
- Extension-discovery UX is undecided (inline prompt when a pipeline needs an uninstalled extension vs. upfront installation from an extensions page). Decision forced at M3.
- Package registry and domain availability for the Formshift name is unverified; web search found no npm/PyPI collision, but that is weak evidence and needs a direct registry check before names calcify.
- No direct competitor was found for either half (Vector's interactive raster prep + tracing + print finishing; the server's typed heterogeneous DAG with caching, permissively licensed and lightweight). Either a genuine gap or a sign nobody thought it worth building; worth staying honest about which.
