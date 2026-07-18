"""Job lifecycle and the per-session event stream (ADR 0007).

Jobs run in worker threads; events accumulate in a per-session append-only
log that SSE generators read. The polling read is an internal choice (free to
churn); the event shapes on the wire are the contract.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .cache import ResultCache
from .executor import ExecutionCancelled, ExecutionOutput, execute_graph
from .graph import Graph
from .modules import ModuleError, ModuleRegistry
from .sessions import Session


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})


@dataclass(frozen=True)
class Event:
    index: int
    type: str
    data: dict[str, Any]

    def sse(self) -> str:
        payload = json.dumps(self.data, separators=(",", ":"))
        return f"id: {self.index}\nevent: {self.type}\ndata: {payload}\n\n"


class EventLog:
    """Append-only per-session event log with a condition for waiters."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._condition = threading.Condition()

    def append(self, type: str, data: dict[str, Any]) -> None:
        with self._condition:
            self._events.append(Event(index=len(self._events), type=type, data=data))
            self._condition.notify_all()

    def since(self, index: int) -> list[Event]:
        with self._condition:
            return self._events[index:]


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    outputs: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def to_json(self) -> dict[str, Any]:
        doc: dict[str, Any] = {"id": self.id, "status": self.status.value}
        if self.status is JobStatus.COMPLETED:
            doc["outputs"] = self.outputs
        if self.error is not None:
            doc["error"] = self.error
        return doc


class JobManager:
    """Owns jobs and the event log for one session."""

    def __init__(
        self,
        session: Session,
        registry: ModuleRegistry,
        cache: ResultCache,
        workers: int | None = None,
    ) -> None:
        self._session = session
        self._registry = registry
        self._cache = cache
        self._workers = workers
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.events = EventLog()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """Request cancellation. True if the job exists (idempotent, ADR 0007)."""
        job = self.get(job_id)
        if job is None:
            return False
        job.cancel.set()
        return True

    def shutdown(self) -> None:
        """Cancel every nonterminal job (session deletion, ADR 0004).

        Worker threads observe the cancel at their next node boundary and
        discard in-flight results, so nothing owned by the session outlives it.
        """
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.status not in TERMINAL:
                job.cancel.set()

    def submit(self, graph: Graph, draft: bool) -> Job:
        """Create a job and start it on a worker thread. Graph is pre-validated."""
        job = Job(id=secrets.token_urlsafe(16))
        with self._lock:
            self._jobs[job.id] = job
        self._set_status(job, JobStatus.PENDING)
        thread = threading.Thread(
            target=self._run, args=(job, graph, draft), name=f"job-{job.id}", daemon=True
        )
        thread.start()
        return job

    def _set_status(self, job: Job, status: JobStatus) -> None:
        job.status = status
        self.events.append("job.status", {"job": job.id, "status": status.value})

    def _run(self, job: Job, graph: Graph, draft: bool) -> None:
        self._set_status(job, JobStatus.RUNNING)

        def on_node(node_id: str, cached: bool) -> None:
            self.events.append("node.completed", {"job": job.id, "node": node_id, "cached": cached})

        def emit_output(output: ExecutionOutput, group: str | None) -> None:
            payload = self._session.add_payload(output.type, output.data)
            record = {
                "node": output.node,
                "port": output.port,
                "type": output.type,
                "payload": payload.id,
            }
            if group is not None:
                record["group"] = group
            job.outputs.append(record)
            self.events.append("job.output", {"job": job.id, **record})

        # Progressive rendering's pinned path (ADR 0014): outputs in a pinned
        # group emit strictly in declared order; a member that finished early
        # is held until everything listed before it has been emitted. Outputs
        # outside pinned groups keep streaming in completion order.
        group_orders = {g.id: g.order for g in graph.groups}
        group_of: dict[tuple[str, str], str | None] = {}
        pinned_sequence: dict[str, list[tuple[str, str]]] = {}
        for ref in graph.outputs:
            key = (ref.node, ref.port)
            group_of[key] = ref.group
            if ref.group is not None and group_orders[ref.group] == "pinned":
                pinned_sequence.setdefault(ref.group, []).append(key)
        held: dict[str, dict[tuple[str, str], ExecutionOutput]] = {}
        next_index: dict[str, int] = dict.fromkeys(pinned_sequence, 0)
        gate = threading.Lock()

        def on_output(output: ExecutionOutput) -> None:
            key = (output.node, output.port)
            group = group_of.get(key)
            if group is None or group not in pinned_sequence:
                emit_output(output, group)
                return
            # Emission happens under the lock so a flush from one worker
            # cannot interleave with another's; event appends are in-memory.
            with gate:
                held.setdefault(group, {})[key] = output
                sequence = pinned_sequence[group]
                while next_index[group] < len(sequence):
                    ready = held[group].pop(sequence[next_index[group]], None)
                    if ready is None:
                        break
                    emit_output(ready, group)
                    next_index[group] += 1

        try:
            execute_graph(
                graph,
                self._registry,
                self._session,
                self._cache,
                draft=draft,
                workers=self._workers,
                on_node=on_node,
                on_output=on_output,
                cancel=job.cancel,
            )
        except ExecutionCancelled:
            self._set_status(job, JobStatus.CANCELLED)
            self.events.append("job.cancelled", {"job": job.id})
        except ModuleError as exc:
            job.error = str(exc)
            self._set_status(job, JobStatus.FAILED)
            self.events.append("job.failed", {"job": job.id, "error": job.error})
        except Exception as exc:  # job boundary: report, never crash the server
            job.error = f"internal error: {exc}"
            self._set_status(job, JobStatus.FAILED)
            self.events.append("job.failed", {"job": job.id, "error": job.error})
        else:
            self._set_status(job, JobStatus.COMPLETED)
            self.events.append("job.completed", {"job": job.id})
