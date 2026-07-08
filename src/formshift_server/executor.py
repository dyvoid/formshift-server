"""Graph executor: validate, topologically walk, execute with caching.

Synchronous by design — job orchestration (threads, progress events,
cancellation) lives above this layer. A linear chain is the degenerate case
of the same topological walk (design doc, Execution model).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from .cache import ResultCache, content_hash, recipe_key
from .graph import Graph, GraphValidationError, topological_order, validate_graph
from .modules import ModuleRegistry, ModuleResult
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
    executed_nodes: tuple[str, ...]  # nodes that actually ran (cache misses)
    cached_nodes: tuple[str, ...]  # nodes served from cache


class ExecutionCancelled(Exception):
    """Raised when a cancel event fires; checked at node boundaries (ADR 0007)."""


# Called after each node completes: (node_id, cached).
NodeCallback = Callable[[str, bool], None]
# Called as each requested output materializes: progressive rendering's
# disjoint path (ADR 0007).
OutputCallback = Callable[[ExecutionOutput], None]


def execute_graph(
    graph: Graph,
    registry: ModuleRegistry,
    session: Session,
    cache: ResultCache,
    *,
    draft: bool = False,
    on_node: NodeCallback | None = None,
    on_output: OutputCallback | None = None,
    cancel: threading.Event | None = None,
) -> ExecutionReport:
    """Execute a validated graph to completion. Raises GraphValidationError if invalid."""
    errors = validate_graph(graph, registry, session)
    if errors:
        raise GraphValidationError(errors)

    order = topological_order(graph)
    assert order is not None  # validated above

    nodes_by_id = {node.id: node for node in graph.nodes}
    # (node, input port) -> the upstream source feeding it
    edge_into: dict[tuple[str, str], tuple[str, str]] = {
        (e.to_node, e.to_port): (e.from_node, e.from_port) for e in graph.edges
    }
    binding_into: dict[tuple[str, str], str] = {(b.node, b.port): b.payload for b in graph.bindings}

    outputs_by_node: dict[str, list[tuple[str, str]]] = {}
    for ref in graph.outputs:
        outputs_by_node.setdefault(ref.node, []).append((ref.node, ref.port))

    node_keys: dict[str, str] = {}
    node_results: dict[str, dict[str, ModuleResult]] = {}
    executed: list[str] = []
    cached: list[str] = []
    emitted_outputs: dict[tuple[str, str], ExecutionOutput] = {}

    for node_id in order:
        if cancel is not None and cancel.is_set():
            raise ExecutionCancelled(f"cancelled before node {node_id!r}")

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
        node_keys[node_id] = cache_key

        hit = cache.get(cache_key)
        if hit is not None:
            node_results[node_id] = hit
            cached.append(node_id)
            was_cached = True
        else:
            results = module.run(inputs, node.params, draft=draft)
            missing = {p.name for p in manifest.outputs} - results.keys()
            if missing:
                raise RuntimeError(
                    f"module {manifest.name!r} did not produce declared outputs: {sorted(missing)}"
                )
            cache.put(cache_key, results)
            node_results[node_id] = results
            executed.append(node_id)
            was_cached = False

        if on_node is not None:
            on_node(node_id, was_cached)

        for out_node, out_port in outputs_by_node.get(node_id, []):
            result = node_results[out_node][out_port]
            output = ExecutionOutput(
                node=out_node, port=out_port, type=result.type, data=result.data
            )
            emitted_outputs[out_node, out_port] = output
            if on_output is not None:
                on_output(output)

    outputs = tuple(emitted_outputs[ref.node, ref.port] for ref in graph.outputs)
    return ExecutionReport(
        outputs=outputs, executed_nodes=tuple(executed), cached_nodes=tuple(cached)
    )
