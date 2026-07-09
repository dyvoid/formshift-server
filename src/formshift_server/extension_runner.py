"""Out-of-process module worker, executed by an extension venv's interpreter.

This file is invoked by path with the *extension's* Python (ADRs 0012/0015);
the formshift_server package is not installed there, so this module must
import nothing beyond the standard library and the extension's own code.

It serves newline-delimited JSON over stdio, one response per request, until
stdin closes:

    request:  {"src": <dir>, "entry": "file:callable", "inputs": {port: b64},
               "params": {...}, "draft": bool}
    response: {"ok": true, "outputs": {port: {"type": str, "data": b64}}}
            | {"ok": false, "error": str}

The entry callable receives (inputs: dict[str, bytes], params: dict, draft:
bool) and returns {port: (type_string, bytes)}. The process is long-lived, so
imports (and whatever the extension caches at module level, e.g. model
sessions) amortize across requests. Anything the extension writes to stdout
would corrupt the protocol channel, so the real stdout is duplicated for
protocol use and fd 1 is redirected to stderr before any extension code runs
— an fd-level guard that catches native libraries too.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import sys
from typing import Any, TextIO


def _run(request: dict[str, Any]) -> dict[str, Any]:
    src = request["src"]
    if src not in sys.path:
        sys.path.insert(0, src)
    module_name, _, attr = request["entry"].partition(":")
    entry = getattr(importlib.import_module(module_name), attr)

    inputs = {port: base64.b64decode(b64) for port, b64 in request["inputs"].items()}
    produced = entry(inputs, request["params"], bool(request["draft"]))

    outputs = {}
    for port, (type_string, data) in produced.items():
        if not isinstance(data, bytes):
            raise TypeError(f"output port {port!r} produced {type(data).__name__}, expected bytes")
        outputs[port] = {"type": type_string, "data": base64.b64encode(data).decode("ascii")}
    return {"ok": True, "outputs": outputs}


def _claim_protocol_channel() -> TextIO:
    """Reserve real stdout for protocol frames; point fd 1 at stderr for everyone else."""
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    return protocol


def serve() -> None:
    protocol = _claim_protocol_channel()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = _run(json.loads(line))
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        protocol.write(json.dumps(response) + "\n")
        protocol.flush()


if __name__ == "__main__":
    serve()
