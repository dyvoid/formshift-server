"""Parallel execution of independent graph branches."""

import threading
import time
from typing import Any

from formshift_server.cache import ResultCache
from formshift_server.executor import execute_graph
from formshift_server.graph import parse_graph
from formshift_server.modules import ModuleManifest, ModuleRegistry, ModuleResult, PortSpec
from formshift_server.sessions import Session

from .helpers import TEXT, ConcatModule


def make_session() -> Session:
    return Session(id="s")


class SleepModule:
    """Sleeps, then echoes. Records how many runs overlap in time."""

    def __init__(self, seconds: float = 0.15) -> None:
        self.manifest = ModuleManifest(
            name="test.sleep",
            version="1.0",
            description="sleep then echo",
            inputs=(PortSpec("text", TEXT),),
            outputs=(PortSpec("text", TEXT),),
        )
        self.seconds = seconds
        self._lock = threading.Lock()
        self._active = 0
        self.max_concurrency = 0

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        with self._lock:
            self._active += 1
            self.max_concurrency = max(self.max_concurrency, self._active)
        time.sleep(self.seconds)
        with self._lock:
            self._active -= 1
        return {"text": ModuleResult(type=TEXT, data=inputs["text"])}


def fanout_graph(payload_id: str, branches: int) -> dict[str, Any]:
    """One payload fanned out to N independent sleep nodes, merged pairwise."""
    nodes = [
        {"id": f"s{i}", "module": "test.sleep", "params": {"branch": i}} for i in range(branches)
    ]
    bindings = [{"payload": payload_id, "node": f"s{i}", "port": "text"} for i in range(branches)]
    outputs = [{"node": f"s{i}", "port": "text"} for i in range(branches)]
    return {"nodes": nodes, "edges": [], "bindings": bindings, "outputs": outputs}


def test_independent_branches_run_concurrently() -> None:
    registry = ModuleRegistry()
    sleeper = SleepModule()
    registry.register(sleeper)
    session = make_session()
    payload = session.add_payload(TEXT, b"x")

    start = time.perf_counter()
    report = execute_graph(
        parse_graph(fanout_graph(payload.id, 4)),
        registry,
        session,
        ResultCache(),
        workers=4,
    )
    elapsed = time.perf_counter() - start

    assert len(report.outputs) == 4
    assert sleeper.max_concurrency >= 2  # branches overlapped
    assert elapsed < 4 * sleeper.seconds  # visibly faster than sequential


def test_workers_one_is_sequential() -> None:
    registry = ModuleRegistry()
    sleeper = SleepModule(seconds=0.05)
    registry.register(sleeper)
    session = make_session()
    payload = session.add_payload(TEXT, b"x")

    execute_graph(
        parse_graph(fanout_graph(payload.id, 4)),
        registry,
        session,
        ResultCache(),
        workers=1,
    )
    assert sleeper.max_concurrency == 1


def test_diamond_dependency_order_respected_under_parallelism() -> None:
    """concat(sleep(x), sleep(x)) must wait for both branches."""
    registry = ModuleRegistry()
    registry.register(SleepModule(seconds=0.05))
    registry.register(ConcatModule())
    session = make_session()
    payload = session.add_payload(TEXT, b"x")

    graph = {
        "nodes": [
            {"id": "a", "module": "test.sleep", "params": {"branch": 1}},
            {"id": "b", "module": "test.sleep", "params": {"branch": 2}},
            {"id": "c", "module": "test.concat"},
        ],
        "edges": [
            {"from_node": "a", "from_port": "text", "to_node": "c", "to_port": "a"},
            {"from_node": "b", "from_port": "text", "to_node": "c", "to_port": "b"},
        ],
        "bindings": [
            {"payload": payload.id, "node": "a", "port": "text"},
            {"payload": payload.id, "node": "b", "port": "text"},
        ],
        "outputs": [{"node": "c", "port": "text"}],
    }
    report = execute_graph(parse_graph(graph), registry, session, ResultCache(), workers=4)
    assert report.outputs[0].data == b"xx"
