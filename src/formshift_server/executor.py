"""Graph executor: validate, then execute ready nodes concurrently with caching.

Independent branches (per-color traces, parallel subtrees of a merge tree)
run concurrently on a thread pool; a linear chain degenerates to sequential
execution through the same scheduler. Synchronous from the caller's view —
job orchestration (threads, progress events, cancellation requests) lives
above this layer.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from .cache import ResultCache, content_hash, recipe_key
from .graph import Graph, GraphValidationError, topological_order, validate_graph
from .modules import ModuleError, ModuleRegistry, ModuleResult
from .sessions import Session


@dataclass(frozen=True)
class ExecutionOutput:
    node: str
    port: str
    type: str
    data: bytes


@dataclass(frozen=True)
class ExecutionReport:
    outputs: tuple[ExecutionOutput, ...]
    executed_nodes: frozenset[str]  # nodes that actually ran (cache misses)
    cached_nodes: frozenset[str]  # nodes served from cache


class ExecutionCancelled(Exception):
    """Raised when a cancel event fires; checked before each node dispatch (ADR 0007)."""


# Called after each node completes: (node_id, cached). May be called from
# worker threads; implementations must be thread-safe.
NodeCallback = Callable[[str, bool], None]
# Called as each requested output materializes (progressive rendering's
# disjoint path, ADR 0007). Same thread-safety requirement.
OutputCallback = Callable[[ExecutionOutput], None]


def default_workers() -> int:
    return os.cpu_count() or 4


def execute_graph(
    graph: Graph,
    registry: ModuleRegistry,
    session: Session,
    cache: ResultCache,
    *,
    draft: bool = False,
    workers: int | None = None,
    on_node: NodeCallback | None = None,
    on_output: OutputCallback | None = None,
    cancel: threading.Event | None = None,
) -> ExecutionReport:
    """Execute a validated graph to completion. Raises GraphValidationError if invalid."""
    errors = validate_graph(graph, registry, session)
    if errors:
        raise GraphValidationError(errors)
    assert topological_order(graph) is not None  # validated above

    nodes_by_id = {node.id: node for node in graph.nodes}
    edge_into: dict[tuple[str, str], tuple[str, str]] = {
        (e.to_node, e.to_port): (e.from_node, e.from_port) for e in graph.edges
    }
    binding_into: dict[tuple[str, str], str] = {(b.node, b.port): b.payload for b in graph.bindings}

    dependencies: dict[str, set[str]] = {node.id: set() for node in graph.nodes}
    dependents: dict[str, set[str]] = {node.id: set() for node in graph.nodes}
    for edge in graph.edges:
        dependencies[edge.to_node].add(edge.from_node)
        dependents[edge.from_node].add(edge.to_node)

    outputs_by_node: dict[str, list[tuple[str, str]]] = {}
    for ref in graph.outputs:
        outputs_by_node.setdefault(ref.node, []).append((ref.node, ref.port))

    # Shared state, guarded by `state_lock`. Node results/keys are written by
    # the worker that ran the node and read only by workers running dependents,
    # which the scheduler starts strictly afterwards.
    node_keys: dict[str, str] = {}
    node_results: dict[str, dict[str, ModuleResult]] = {}
    executed: set[str] = set()
    cached: set[str] = set()
    emitted_outputs: dict[tuple[str, str], ExecutionOutput] = {}
    state_lock = threading.Lock()

    def run_node(node_id: str) -> str:
        node = nodes_by_id[node_id]
        module = registry.get(node.module)
        assert module is not None  # validated above
        manifest = module.manifest

        input_keys: list[str] = []
        inputs: dict[str, bytes] = {}
        for port in manifest.inputs:
            key = (node_id, port.name)
            if key in binding_into:
                payload = session.payloads[binding_into[key]]
                input_keys.append(content_hash(payload.data))
                inputs[port.name] = payload.data
            else:
                src_node, src_port = edge_into[key]
                input_keys.append(node_keys[src_node])
                inputs[port.name] = node_results[src_node][src_port].data

        cache_key = recipe_key(manifest.name, manifest.version, node.params, input_keys, draft)

        hit = cache.get(cache_key)
        if hit is not None:
            results = hit
            was_cached = True
        else:
            results = module.run(inputs, node.params, draft=draft)
            # Enforce the manifest contract before anything reaches the cache:
            # a violating result must never poison it (or downstream nodes).
            declared = {p.name: p.type for p in manifest.outputs}
            missing = declared.keys() - results.keys()
            if missing:
                raise ModuleError(
                    f"module {manifest.name!r} missing declared outputs: {sorted(missing)}"
                )
            extra = results.keys() - declared.keys()
            if extra:
                raise ModuleError(
                    f"module {manifest.name!r} returned undeclared outputs: {sorted(extra)}"
                )
            for name, result in results.items():
                if result.type != declared[name]:
                    raise ModuleError(
                        f"module {manifest.name!r} output {name!r} has wrong type "
                        f"{result.type!r} (declared {declared[name]!r})"
                    )
            if cancel is not None and cancel.is_set():
                # The job was cancelled while this node ran; drop the result so
                # a deleted session leaves no trace in the shared cache.
                raise ExecutionCancelled("cancelled at node boundary")
            cache.put(cache_key, results)
            was_cached = False

        with state_lock:
            node_keys[node_id] = cache_key
            node_results[node_id] = results
            (cached if was_cached else executed).add(node_id)

        if on_node is not None:
            on_node(node_id, was_cached)

        for out_node, out_port in outputs_by_node.get(node_id, []):
            result = results[out_port]
            output = ExecutionOutput(
                node=out_node, port=out_port, type=result.type, data=result.data
            )
            with state_lock:
                emitted_outputs[out_node, out_port] = output
            if on_output is not None:
                on_output(output)
        return node_id

    remaining_deps = {node_id: set(deps) for node_id, deps in dependencies.items()}
    ready = [node_id for node_id, deps in remaining_deps.items() if not deps]
    in_flight: dict[Future[str], str] = {}
    max_workers = workers if workers is not None else default_workers()

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        while ready or in_flight:
            if cancel is not None and cancel.is_set():
                # Stop dispatching; let in-flight nodes finish (node-boundary
                # cancellation, ADR 0007), then report.
                wait(list(in_flight))
                raise ExecutionCancelled("cancelled at node boundary")

            for node_id in ready:
                in_flight[pool.submit(run_node, node_id)] = node_id
            ready = []

            done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                finished = in_flight.pop(future)
                future.result()  # re-raises module/executor errors
                for dependent in dependents[finished]:
                    deps = remaining_deps[dependent]
                    deps.discard(finished)
                    if not deps:
                        ready.append(dependent)

    outputs = tuple(emitted_outputs[ref.node, ref.port] for ref in graph.outputs)
    return ExecutionReport(
        outputs=outputs, executed_nodes=frozenset(executed), cached_nodes=frozenset(cached)
    )
