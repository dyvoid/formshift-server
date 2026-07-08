"""Command-line entry point.

Standalone-process daemon hygiene per the design doc's Deployment model:
`--port 0` lets the OS pick a free port and the chosen port is reported on
stdout; connection info (including the token) prints at startup; binding
beyond loopback without an explicit token is a startup error (ADR 0003).
"""

from __future__ import annotations

import argparse
import os
import socket
import sys

import uvicorn

from .app import create_app
from .config import ServerConfig, generate_token


def _build_config(argv: list[str] | None = None) -> ServerConfig:
    parser = argparse.ArgumentParser(prog="formshift-server")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default loopback)")
    parser.add_argument("--port", type=int, default=7457, help="Port to bind; 0 = OS-assigned")
    parser.add_argument("--token", default=None, help="Auth token (overrides FORMSHIFT_TOKEN)")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker threads per job for independent graph branches (default: CPU count)",
    )
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("FORMSHIFT_TOKEN")
    config = ServerConfig(
        host=args.host,
        port=args.port,
        token=token or generate_token(),
        token_explicit=token is not None,
        workers=args.workers,
    )
    config.validate()
    return config


def main(argv: list[str] | None = None) -> None:
    try:
        config = _build_config(argv)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    app = create_app(config)

    # Bind the socket ourselves so `--port 0` can report the real port before
    # the server starts accepting connections.
    family = socket.AF_INET6 if ":" in config.host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((config.host, config.port))
    actual_port = sock.getsockname()[1]

    print(f"formshift-server listening on http://{config.host}:{actual_port}", flush=True)
    print(f"token: {config.token}", flush=True)

    server = uvicorn.Server(uvicorn.Config(app, log_level="info"))
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
