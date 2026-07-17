"""Server configuration.

Security defaults follow ADR 0003: loopback binding, token auth always on,
localhost-only Host/Origin allowlist.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Host/Origin allowlist entries are compared against the hostname with any
# port stripped (ADR 0003: "localhost forms only, any port").
DEFAULT_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})


def generate_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 7457
    token: str = field(default_factory=generate_token)
    # True when the token came from a flag/env rather than startup generation;
    # non-loopback binding requires this (ADR 0003).
    token_explicit: bool = False
    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS
    cors_origins: tuple[str, ...] = ()
    # Worker threads per job for independent graph branches; None = cpu count.
    workers: int | None = None
    # Where installed extensions (their venvs and copied sources) live.
    # None = extension installation disabled; the embedding app opts in
    # explicitly, because installing an extension executes downloaded code
    # (ADR 0013).
    extensions_dir: Path | None = None

    def validate(self) -> None:
        if self.host not in LOOPBACK_HOSTS and not self.token_explicit:
            raise ValueError(
                f"refusing to bind non-loopback interface {self.host!r} without an "
                "explicitly configured token (--token or FORMSHIFT_TOKEN)"
            )
