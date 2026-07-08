"""Graph executor: validate, topologically walk, execute with caching.

Synchronous by design — job orchestration (threads, progress events,
cancellation) lives above this layer. A linear chain is the degenerate case
of the same topological walk (design doc, Execution model).
"""

from __future__ import annotations

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


def execute_graph(
    graph: Graph,
    registry: ModuleRegistry,
    session: Session,
    cache: ResultCache,
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

    node_keys: dict[str, str] = {}
    node_results: dict[str, dict[str, ModuleResult]] = {}
    executed: list[str] = []
    cached: list[str] = []

    for node_id in order:
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

        cache_key = recipe_key(manifest.name, manifest.version, node.params, input_keys)
        node_keys[node_id] = cache_key

        hit = cache.get(cache_key)
        if hit is not None:
            node_results[node_id] = hit
            cached.append(node_id)
            continue

        results = module.run(inputs, node.params)
        missing = {p.name for p in manifest.outputs} - results.keys()
        if missing:
            raise RuntimeError(
                f"module {manifest.name!r} did not produce declared outputs: {sorted(missing)}"
            )
        cache.put(cache_key, results)
        node_results[node_id] = results
        executed.append(node_id)

    outputs = tuple(
        ExecutionOutput(
            node=ref.node,
            port=ref.port,
            type=node_results[ref.node][ref.port].type,
            data=node_results[ref.node][ref.port].data,
        )
        for ref in graph.outputs
    )
    return ExecutionReport(
        outputs=outputs, executed_nodes=tuple(executed), cached_nodes=tuple(cached)
    )
