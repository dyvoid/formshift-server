"""Graph parsing, validation, and topological ordering (ADR 0005)."""

from typing import Any

from formshift_server.graph import parse_graph, topological_order, validate_graph
from formshift_server.modules import ModuleRegistry
from formshift_server.sessions import Session

from .helpers import TEXT, ConcatModule, SuffixModule, UpperModule


def make_registry() -> ModuleRegistry:
    registry = ModuleRegistry()
    registry.register(UpperModule())
    registry.register(SuffixModule())
    registry.register(ConcatModule())
    return registry


def make_session_with_payload(data: bytes = b"hello") -> tuple[Session, str]:
    session = Session(id="s1")
    payload = session.add_payload(TEXT, data)
    return session, payload.id


def linear_graph(payload_id: str) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "up", "module": "test.upper"},
            {"id": "suf", "module": "test.suffix", "params": {"suffix": "!"}},
        ],
        "edges": [{"from_node": "up", "from_port": "text", "to_node": "suf", "to_port": "text"}],
        "bindings": [{"payload": payload_id, "node": "up", "port": "text"}],
        "outputs": [{"node": "suf", "port": "text"}],
    }


def test_valid_linear_graph_passes() -> None:
    session, payload_id = make_session_with_payload()
    graph = parse_graph(linear_graph(payload_id))
    assert validate_graph(graph, make_registry(), session) == []


def test_unknown_fields_are_ignored() -> None:
    session, payload_id = make_session_with_payload()
    data = linear_graph(payload_id)
    data["future_field"] = {"anything": True}
    data["nodes"][0]["another_future_field"] = 1
    graph = parse_graph(data)
    assert validate_graph(graph, make_registry(), session) == []


def test_unknown_module_reported() -> None:
    session, payload_id = make_session_with_payload()
    data = linear_graph(payload_id)
    data["nodes"][0]["module"] = "test.nope"
    errors = validate_graph(parse_graph(data), make_registry(), session)
    assert any("unknown module" in e for e in errors)


def test_duplicate_node_id_reported() -> None:
    session, payload_id = make_session_with_payload()
    data = linear_graph(payload_id)
    data["nodes"].append({"id": "up", "module": "test.upper"})
    errors = validate_graph(parse_graph(data), make_registry(), session)
    assert any("duplicate node id" in e for e in errors)


def test_type_mismatch_reported() -> None:
    session = Session(id="s1")
    payload = session.add_payload("raster/png", b"pngbytes")
    data = linear_graph(payload.id)
    errors = validate_graph(parse_graph(data), make_registry(), session)
    assert any("does not match port" in e for e in errors)


def test_unfed_input_reported() -> None:
    session, payload_id = make_session_with_payload()
    data = linear_graph(payload_id)
    data["bindings"] = []
    errors = validate_graph(parse_graph(data), make_registry(), session)
    assert any("is not fed" in e for e in errors)


def test_doubly_fed_input_reported() -> None:
    session, payload_id = make_session_with_payload()
    data = linear_graph(payload_id)
    data["bindings"].append({"payload": payload_id, "node": "suf", "port": "text"})
    errors = validate_graph(parse_graph(data), make_registry(), session)
    assert any("fed 2 times" in e for e in errors)


def test_cycle_reported() -> None:
    session, _payload_id = make_session_with_payload()
    data = {
        "nodes": [
            {"id": "a", "module": "test.upper"},
            {"id": "b", "module": "test.upper"},
        ],
        "edges": [
            {"from_node": "a", "from_port": "text", "to_node": "b", "to_port": "text"},
            {"from_node": "b", "from_port": "text", "to_node": "a", "to_port": "text"},
        ],
        "bindings": [],
        "outputs": [{"node": "b", "port": "text"}],
    }
    errors = validate_graph(parse_graph(data), make_registry(), session)
    assert any("cycle" in e for e in errors)


def test_unknown_payload_reported() -> None:
    session, _ = make_session_with_payload()
    data = linear_graph("nonexistent-payload")
    errors = validate_graph(parse_graph(data), make_registry(), session)
    assert any("unknown payload" in e for e in errors)


def test_no_outputs_reported() -> None:
    session, payload_id = make_session_with_payload()
    data = linear_graph(payload_id)
    data["outputs"] = []
    errors = validate_graph(parse_graph(data), make_registry(), session)
    assert any("no outputs" in e for e in errors)


def test_topological_order_respects_edges() -> None:
    _session, payload_id = make_session_with_payload()
    graph = parse_graph(linear_graph(payload_id))
    order = topological_order(graph)
    assert order is not None
    assert order.index("up") < order.index("suf")
