"""Out-of-process module runner, executed by an extension venv's interpreter.

This file is invoked by path with the *extension's* Python (ADR 0012); the
formshift_server package is not installed there, so this module must import
nothing beyond the standard library and the extension's own code. It speaks
one JSON request on stdin, one JSON response on stdout:

    request:  {"src": <dir>, "entry": "file:callable", "inputs": {port: b64},
               "params": {...}, "draft": bool}
    response: {"ok": true, "outputs": {port: {"type": str, "data": b64}}}
            | {"ok": false, "error": str}

The entry callable receives (inputs: dict[str, bytes], params: dict, draft:
bool) and returns {port: (type_string, bytes)}. Anything the extension prints
to stdout would corrupt the response channel, so stdout is redirected to
stderr around the call.
"""

from __future__ import annotations

import base64
import contextlib
import importlib
import json
import sys
from typing import Any


def _run(request: dict[str, Any]) -> dict[str, Any]:
    sys.path.insert(0, request["src"])
    module_name, _, attr = request["entry"].partition(":")
    entry = getattr(importlib.import_module(module_name), attr)

    inputs = {port: base64.b64decode(b64) for port, b64 in request["inputs"].items()}
    with contextlib.redirect_stdout(sys.stderr):
        produced = entry(inputs, request["params"], bool(request["draft"]))

    outputs = {}
    for port, (type_string, data) in produced.items():
        if not isinstance(data, bytes):
            raise TypeError(f"output port {port!r} produced {type(data).__name__}, expected bytes")
        outputs[port] = {"type": type_string, "data": base64.b64encode(data).decode("ascii")}
    return {"ok": True, "outputs": outputs}


def main() -> None:
    try:
        response = _run(json.load(sys.stdin))
    except Exception as exc:
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    json.dump(response, sys.stdout)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
