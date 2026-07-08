"""Hash-chain cache (ADR 0006): recipe-hash keys, content-hashed roots.

Keys are internal — never exposed on the wire — so the keying scheme can
evolve without a contract break. In-memory and unbounded for now; the
budget/eviction policy is a flagged open point (M5).
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from .modules import ModuleResult


def content_hash(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def recipe_key(
    module_name: str,
    module_version: str,
    params: dict[str, Any],
    input_keys: list[str],
    draft: bool = False,
) -> str:
    """Cache key for one node: its own recipe plus its inputs' keys, in port order.

    Draft is part of the key: a draft result must never be served for a
    full-quality request (ADR 0007).
    """
    canonical = json.dumps(
        {
            "module": module_name,
            "version": module_version,
            "params": params,
            "inputs": input_keys,
            "draft": draft,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.blake2b(canonical.encode(), digest_size=16).hexdigest()


class ResultCache:
    """Maps cache key -> per-output-port results for one node execution."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, ModuleResult]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, ModuleResult] | None:
        with self._lock:
            return self._entries.get(key)

    def put(self, key: str, results: dict[str, ModuleResult]) -> None:
        with self._lock:
            self._entries[key] = results

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
