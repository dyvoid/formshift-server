"""Executor and hash-chain cache behavior (ADR 0006)."""

from typing import Any

import pytest

from formshift_server.cache import ResultCache
from formshift_server.executor import execute_graph
from formshift_server.graph import GraphValidationError, parse_graph
from formshift_server.modules import ModuleRegistry
from formshift_server.sessions import Session

from .helpers import TEXT, ConcatModule, SuffixModule, UpperModule


def make_modules() -> tuple[ModuleRegistry, UpperModule, SuffixModule, ConcatModule]:
    registry = ModuleRegistry()
    upper = UpperModule()
    suffix = SuffixModule()
    concat = ConcatModule()
    registry.register(upper)
    registry.register(suffix)
    registry.register(concat)
    return registry, upper, suffix, concat


def linear_graph(payload_id: str, suffix: str = "!") -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "up", "module": "test.upper"},
            {"id": "suf", "module": "test.suffix", "params": {"suffix": suffix}},
        ],
        "edges": [{"from_node": "up", "from_port": "text", "to_node": "suf", "to_port": "text"}],
        "bindings": [{"payload": payload_id, "node": "up", "port": "text"}],
        "outputs": [{"node": "suf", "port": "text"}],
    }


def test_linear_execution_produces_output() -> None:
    registry, *_ = make_modules()
    session = Session(id="s")
    payload = session.add_payload(TEXT, b"hello")
    cache = ResultCache()

    report = execute_graph(parse_graph(linear_graph(payload.id)), registry, session, cache)

    assert len(report.outputs) == 1
    assert report.outputs[0].data == b"HELLO!"
    assert report.outputs[0].type == TEXT
    assert report.executed_nodes == {"up", "suf"}
    assert report.cached_nodes == frozenset()


def test_rerun_is_fully_cached() -> None:
    registry, upper, suffix, _ = make_modules()
    session = Session(id="s")
    payload = session.add_payload(TEXT, b"hello")
    cache = ResultCache()

    execute_graph(parse_graph(linear_graph(payload.id)), registry, session, cache)
    report = execute_graph(parse_graph(linear_graph(payload.id)), registry, session, cache)

    assert report.cached_nodes == {"up", "suf"}
    assert report.executed_nodes == frozenset()
    assert upper.runs == 1
    assert suffix.runs == 1
    assert report.outputs[0].data == b"HELLO!"


def test_param_change_reruns_only_downstream() -> None:
    registry, upper, suffix, _ = make_modules()
    session = Session(id="s")
    payload = session.add_payload(TEXT, b"hello")
    cache = ResultCache()

    execute_graph(parse_graph(linear_graph(payload.id, "!")), registry, session, cache)
    report = execute_graph(parse_graph(linear_graph(payload.id, "?")), registry, session, cache)

    assert upper.runs == 1  # upstream untouched
    assert suffix.runs == 2  # downstream of the change reruns
    assert report.cached_nodes == {"up"}
    assert report.executed_nodes == {"suf"}
    assert report.outputs[0].data == b"HELLO?"


def test_identical_reupload_hits_cache() -> None:
    registry, upper, _, _ = make_modules()
    session = Session(id="s")
    first = session.add_payload(TEXT, b"hello")
    second = session.add_payload(TEXT, b"hello")  # same bytes, new payload ID
    cache = ResultCache()

    execute_graph(parse_graph(linear_graph(first.id)), registry, session, cache)
    report = execute_graph(parse_graph(linear_graph(second.id)), registry, session, cache)

    assert upper.runs == 1  # content-hashed root: identical bytes, same key
    assert report.cached_nodes == {"up", "suf"}


def test_multi_input_order_is_part_of_the_key() -> None:
    registry, _, _, concat = make_modules()
    session = Session(id="s")
    pa = session.add_payload(TEXT, b"A")
    pb = session.add_payload(TEXT, b"B")
    cache = ResultCache()

    def concat_graph(first: str, second: str) -> dict[str, Any]:
        return {
            "nodes": [{"id": "c", "module": "test.concat"}],
            "edges": [],
            "bindings": [
                {"payload": first, "node": "c", "port": "a"},
                {"payload": second, "node": "c", "port": "b"},
            ],
            "outputs": [{"node": "c", "port": "text"}],
        }

    r1 = execute_graph(parse_graph(concat_graph(pa.id, pb.id)), registry, session, cache)
    r2 = execute_graph(parse_graph(concat_graph(pb.id, pa.id)), registry, session, cache)

    assert r1.outputs[0].data == b"AB"
    assert r2.outputs[0].data == b"BA"
    assert concat.runs == 2  # swapped inputs must not share a cache entry


def test_invalid_graph_raises_before_any_run() -> None:
    registry, upper, _, _ = make_modules()
    session = Session(id="s")
    cache = ResultCache()
    data = linear_graph("missing-payload")

    with pytest.raises(GraphValidationError):
        execute_graph(parse_graph(data), registry, session, cache)
    assert upper.runs == 0


def test_isolation_other_than_core_is_explicit_not_implemented() -> None:
    from formshift_server.modules import ModuleManifest, PortSpec

    class IsolatedModule:
        manifest = ModuleManifest(
            name="test.isolated",
            version="1.0",
            description="",
            inputs=(PortSpec("text", TEXT),),
            outputs=(PortSpec("text", TEXT),),
            isolation="venv",
        )

        def run(
            self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
        ) -> dict[str, Any]:
            return {}

    registry = ModuleRegistry()
    with pytest.raises(NotImplementedError, match="isolation"):
        registry.register(IsolatedModule())
