"""Graph data model and validation (ADR 0005).

The wire format is JSON; these dataclasses are its parsed form. Validation
happens server-side, in full, before any module runs: unique node IDs, known
modules, existing ports, strict type matching, every input fed exactly once,
acyclicity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from typing import Any

from .modules import ModuleRegistry
from .sessions import Session


@dataclass(frozen=True)
class Node:
    id: str
    module: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    from_node: str
    from_port: str
    to_node: str
    to_port: str


@dataclass(frozen=True)
class Binding:
    payload: str
    node: str
    port: str


@dataclass(frozen=True)
class OutputRef:
    node: str
    port: str
    # Optional membership in a declared output group (ADR 0014).
    group: str | None = None


# Emission-order semantics for one output group (ADR 0014): "completion" is
# the disjoint path (stream as results land); "pinned" holds each member's
# emission until every member listed before it has been emitted.
OUTPUT_GROUP_ORDERS = frozenset({"completion", "pinned"})


@dataclass(frozen=True)
class OutputGroup:
    id: str
    order: str


@dataclass(frozen=True)
class Graph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    bindings: tuple[Binding, ...]
    outputs: tuple[OutputRef, ...]
    groups: tuple[OutputGroup, ...] = ()


class GraphValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_graph(data: dict[str, Any]) -> Graph:
    """Parse the JSON wire format. Unknown fields are ignored (forward-only rule)."""
    try:
        nodes = tuple(
            Node(id=n["id"], module=n["module"], params=dict(n.get("params", {})))
            for n in data.get("nodes", [])
        )
        edges = tuple(
            Edge(
                from_node=e["from_node"],
                from_port=e["from_port"],
                to_node=e["to_node"],
                to_port=e["to_port"],
            )
            for e in data.get("edges", [])
        )
        bindings = tuple(
            Binding(payload=b["payload"], node=b["node"], port=b["port"])
            for b in data.get("bindings", [])
        )
        outputs = tuple(
            OutputRef(node=o["node"], port=o["port"], group=o.get("group"))
            for o in data.get("outputs", [])
        )
        groups = tuple(
            OutputGroup(id=g["id"], order=str(g.get("order", "completion")))
            for g in data.get("groups", [])
        )
    except (KeyError, TypeError) as exc:
        raise GraphValidationError([f"malformed graph: {exc!r}"]) from exc
    return Graph(nodes=nodes, edges=edges, bindings=bindings, outputs=outputs, groups=groups)


def validate_graph(graph: Graph, registry: ModuleRegistry, session: Session) -> list[str]:
    """Return all validation errors (empty list = valid)."""
    errors: list[str] = []
    nodes_by_id: dict[str, Node] = {}

    for node in graph.nodes:
        if node.id in nodes_by_id:
            errors.append(f"duplicate node id {node.id!r}")
        nodes_by_id[node.id] = node
        if registry.get(node.module) is None:
            errors.append(f"node {node.id!r}: unknown module {node.module!r}")

    if not graph.nodes:
        errors.append("graph has no nodes")
    if not graph.outputs:
        errors.append("graph declares no outputs")

    def output_type(node_id: str, port: str) -> str | None:
        node = nodes_by_id.get(node_id)
        module = registry.get(node.module) if node else None
        spec = module.manifest.output_port(port) if module else None
        return spec.type if spec else None

    def input_type(node_id: str, port: str) -> str | None:
        node = nodes_by_id.get(node_id)
        module = registry.get(node.module) if node else None
        spec = module.manifest.input_port(port) if module else None
        return spec.type if spec else None

    fed: dict[tuple[str, str], int] = {}

    for edge in graph.edges:
        src_type = output_type(edge.from_node, edge.from_port)
        dst_type = input_type(edge.to_node, edge.to_port)
        if src_type is None:
            errors.append(f"edge from unknown port {edge.from_node!r}:{edge.from_port!r}")
        if dst_type is None:
            errors.append(f"edge to unknown port {edge.to_node!r}:{edge.to_port!r}")
        if src_type is not None and dst_type is not None and src_type != dst_type:
            errors.append(
                f"type mismatch on edge {edge.from_node}:{edge.from_port} -> "
                f"{edge.to_node}:{edge.to_port}: {src_type!r} != {dst_type!r}"
            )
        fed[edge.to_node, edge.to_port] = fed.get((edge.to_node, edge.to_port), 0) + 1

    for binding in graph.bindings:
        dst_type = input_type(binding.node, binding.port)
        if dst_type is None:
            errors.append(f"binding to unknown port {binding.node!r}:{binding.port!r}")
        payload = session.payloads.get(binding.payload)
        if payload is None:
            errors.append(f"binding references unknown payload {binding.payload!r}")
        elif dst_type is not None and payload.type != dst_type:
            errors.append(
                f"binding payload type {payload.type!r} does not match port "
                f"{binding.node}:{binding.port} type {dst_type!r}"
            )
        fed[binding.node, binding.port] = fed.get((binding.node, binding.port), 0) + 1

    for node in graph.nodes:
        module = registry.get(node.module)
        if module is None:
            continue
        for port in module.manifest.inputs:
            count = fed.get((node.id, port.name), 0)
            if count == 0:
                errors.append(f"input port {node.id}:{port.name} is not fed")
            elif count > 1:
                errors.append(f"input port {node.id}:{port.name} is fed {count} times")

    groups_by_id: dict[str, OutputGroup] = {}
    for group in graph.groups:
        if not group.id:
            errors.append("output group without an id")
        if group.id in groups_by_id:
            errors.append(f"duplicate output group id {group.id!r}")
        groups_by_id[group.id] = group
        if group.order not in OUTPUT_GROUP_ORDERS:
            errors.append(
                f"output group {group.id!r}: unknown order {group.order!r} "
                f"(implemented: {sorted(OUTPUT_GROUP_ORDERS)})"
            )

    for out in graph.outputs:
        if output_type(out.node, out.port) is None:
            errors.append(f"output references unknown port {out.node!r}:{out.port!r}")
        if out.group is not None and out.group not in groups_by_id:
            errors.append(
                f"output {out.node}:{out.port} references undeclared group {out.group!r}"
            )

    if topological_order(graph) is None:
        errors.append("graph contains a cycle")

    return errors


def topological_order(graph: Graph) -> list[str] | None:
    """Node IDs in execution order, or None if the graph has a cycle."""
    sorter: TopologicalSorter[str] = TopologicalSorter()
    for node in graph.nodes:
        sorter.add(node.id)
    for edge in graph.edges:
        sorter.add(edge.to_node, edge.from_node)
    try:
        return list(sorter.static_order())
    except CycleError:
        return None
