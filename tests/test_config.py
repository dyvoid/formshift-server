"""Config validation and CLI config assembly (ADR 0003)."""

import pytest

from formshift_server.cli import _build_config
from formshift_server.config import ServerConfig


def test_default_config_is_loopback_with_generated_token() -> None:
    config = ServerConfig()
    config.validate()
    assert config.host == "127.0.0.1"
    assert len(config.token) > 20


def test_non_loopback_without_explicit_token_is_error() -> None:
    config = ServerConfig(host="0.0.0.0", token_explicit=False)
    with pytest.raises(ValueError, match="refusing to bind"):
        config.validate()


def test_non_loopback_with_explicit_token_is_allowed() -> None:
    config = ServerConfig(host="0.0.0.0", token="secret", token_explicit=True)
    config.validate()


def test_cli_token_flag_marks_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORMSHIFT_TOKEN", raising=False)
    config = _build_config(["--token", "abc"])
    assert config.token == "abc"
    assert config.token_explicit


def test_cli_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORMSHIFT_TOKEN", "from-env")
    config = _build_config([])
    assert config.token == "from-env"
    assert config.token_explicit


def test_cli_flag_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORMSHIFT_TOKEN", "from-env")
    config = _build_config(["--token", "from-flag"])
    assert config.token == "from-flag"


def test_cli_generates_token_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORMSHIFT_TOKEN", raising=False)
    config = _build_config([])
    assert config.token
    assert not config.token_explicit


def test_cli_accepts_repeatable_cors_origins() -> None:
    config = _build_config(
        [
            "--cors-origin",
            "http://localhost:5173",
            "--cors-origin",
            "http://127.0.0.1:5173",
        ]
    )
    assert config.cors_origins == ("http://localhost:5173", "http://127.0.0.1:5173")
