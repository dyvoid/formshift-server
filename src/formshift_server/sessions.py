"""In-memory session and payload store (ADR 0004).

Sessions are the unit of state; payloads are opaque bytes tagged with a type
string. Persistence across restarts is deliberately not promised by the
contract, so an in-memory dict is a valid implementation, not a shortcut.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field


def _new_id() -> str:
    return secrets.token_urlsafe(16)


@dataclass(frozen=True)
class Payload:
    id: str
    type: str
    data: bytes


@dataclass
class Session:
    id: str
    payloads: dict[str, Payload] = field(default_factory=dict)

    def add_payload(self, type_string: str, data: bytes) -> Payload:
        payload = Payload(id=_new_id(), type=type_string, data=data)
        self.payloads[payload.id] = payload
        return payload


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        session = Session(id=_new_id())
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None
