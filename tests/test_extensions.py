"""Extension isolation (ADR 0012) and the /v1/extensions surface (ADR 0013).

The fixture extension is stdlib-only, so installs exercise the real venv
creation and runner subprocess without any network. Tests that pip-install
real conflicting pins are gated behind FORMSHIFT_TEST_NETWORK=1 and live in
test_extension_conflict_e2e.py.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from formshift_server.app import create_app
from formshift_server.config import ServerConfig
from formshift_server.extensions import (
    ExtensionConflictError,
    ExtensionError,
    ExtensionManager,
    parse_extension_manifest,
)
from formshift_server.modules import ModuleManifest, ModuleRegistry, PortSpec

from .conftest import TEST_TOKEN
from .helpers import UpperModule

SHOUT_MANIFEST = """\
[extension]
name = "shout"
version = "0.1.0"
description = "stdlib-only test extension"
requirements = []

[[modules]]
name = "text.shout"
description = "uppercase text, out of process"
entry = "shout:run"
[[modules.inputs]]
name = "text"
type = "text/plain"
[[modules.outputs]]
name = "text"
type = "text/plain"
"""

SHOUT_CODE = '''\
def run(inputs, params, draft):
    text = inputs["text"].upper()
    if params.get("crash"):
        raise RuntimeError("asked to crash")
    if params.get("exclaim"):
        text += b"!"
    return {"text": ("text/plain", text)}
'''


def write_shout_extension(directory: Path) -> Path:
    source = directory / "shout-src"
    source.mkdir()
    (source / "extension.toml").write_text(SHOUT_MANIFEST, encoding="utf-8")
    (source / "shout.py").write_text(SHOUT_CODE, encoding="utf-8")
    return source


@pytest.fixture
def shout_source(tmp_path: Path) -> Path:
    return write_shout_extension(tmp_path)


@pytest.fixture
def manager(tmp_path: Path) -> ExtensionManager:
    return ExtensionManager(tmp_path / "extensions", ModuleRegistry())


# --- manifest parsing ---


def test_parse_valid_manifest(shout_source: Path) -> None:
    manifest = parse_extension_manifest(shout_source)
    assert manifest.name == "shout"
    assert manifest.isolation == "isolated"
    assert manifest.requirements == ()
    (module,) = manifest.modules
    assert module.manifest.name == "text.shout"
    assert module.manifest.isolation == "isolated"
    assert module.manifest.version == "0.1.0"  # cache keys track the extension release
    assert module.entry == "shout:run"


def test_parse_rejects_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(ExtensionError, match=r"no extension\.toml"):
        parse_extension_manifest(tmp_path)


def _manifest_variant(tmp_path: Path, replace: str, with_: str) -> Path:
    source = tmp_path / "variant"
    source.mkdir()
    (source / "extension.toml").write_text(
        SHOUT_MANIFEST.replace(replace, with_), encoding="utf-8"
    )
    (source / "shout.py").write_text(SHOUT_CODE, encoding="utf-8")
    return source


def test_parse_rejects_bad_name(tmp_path: Path) -> None:
    source = _manifest_variant(tmp_path, 'name = "shout"', 'name = "../evil"')
    with pytest.raises(ExtensionError, match="invalid extension name"):
        parse_extension_manifest(source)


def test_parse_rejects_bad_entry(tmp_path: Path) -> None:
    source = _manifest_variant(tmp_path, 'entry = "shout:run"', 'entry = "shout run"')
    with pytest.raises(ExtensionError, match="entry must be"):
        parse_extension_manifest(source)


def test_parse_rejects_unknown_isolation(tmp_path: Path) -> None:
    source = _manifest_variant(
        tmp_path, '[extension]', '[extension]\nisolation = "shared-gpu"'
    )
    with pytest.raises(NotImplementedError, match="shared-gpu"):
        parse_extension_manifest(source)


# --- registry isolation invariants ---


def test_register_rejects_isolated_manifest_in_process() -> None:
    registry = ModuleRegistry()
    module = UpperModule()
    module.manifest = ModuleManifest(
        name="test.upper",
        version="1.0",
        description="claims isolation it does not have",
        inputs=(PortSpec("text", "text/plain"),),
        outputs=(PortSpec("text", "text/plain"),),
        isolation="isolated",
    )
    with pytest.raises(NotImplementedError, match="in-process registration"):
        registry.register(module)


def test_register_isolated_rejects_core_manifest() -> None:
    registry = ModuleRegistry()
    with pytest.raises(NotImplementedError, match="isolated registration"):
        registry.register_isolated(UpperModule())


# --- install + run, no network ---


def test_install_and_run_out_of_process(
    manager: ExtensionManager, shout_source: Path
) -> None:
    installed = manager.install(shout_source)
    assert installed.manifest.name == "shout"
    assert (installed.root / "venv").is_dir()
    assert (installed.root / "src" / "shout.py").is_file()
    assert (installed.root / "installed.json").is_file()

    module = manager._registry.get("text.shout")
    assert module is not None
    results = module.run({"text": b"quiet words"}, {"exclaim": True})
    assert results["text"].data == b"QUIET WORDS!"
    assert results["text"].type == "text/plain"


def test_module_error_surfaces_from_subprocess(
    manager: ExtensionManager, shout_source: Path
) -> None:
    from formshift_server.modules import ModuleError

    manager.install(shout_source)
    module = manager._registry.get("text.shout")
    assert module is not None
    with pytest.raises(ModuleError, match="asked to crash"):
        module.run({"text": b"x"}, {"crash": True})


def test_install_twice_conflicts(manager: ExtensionManager, shout_source: Path) -> None:
    manager.install(shout_source)
    with pytest.raises(ExtensionConflictError, match="already installed"):
        manager.install(shout_source)


def test_install_rejects_module_name_collision(tmp_path: Path, shout_source: Path) -> None:
    registry = ModuleRegistry()
    upper = UpperModule()
    upper.manifest = ModuleManifest(
        name="text.shout",
        version="1.0",
        description="occupies the name",
        inputs=(PortSpec("text", "text/plain"),),
        outputs=(PortSpec("text", "text/plain"),),
    )
    registry.register(upper)
    manager = ExtensionManager(tmp_path / "extensions", registry)
    with pytest.raises(ExtensionConflictError, match="already registered"):
        manager.install(shout_source)
    assert not (tmp_path / "extensions" / "shout").exists()  # nothing half-installed


def test_load_installed_after_restart(tmp_path: Path, shout_source: Path) -> None:
    extensions_dir = tmp_path / "extensions"
    first = ExtensionManager(extensions_dir, ModuleRegistry())
    first.install(shout_source)

    registry = ModuleRegistry()
    second = ExtensionManager(extensions_dir, registry)
    loaded = second.load_installed()
    assert [e.manifest.name for e in loaded] == ["shout"]
    module = registry.get("text.shout")
    assert module is not None
    assert module.run({"text": b"hi"}, {})["text"].data == b"HI"


def test_load_installed_skips_incomplete_installs(tmp_path: Path) -> None:
    extensions_dir = tmp_path / "extensions"
    (extensions_dir / "broken" / "src").mkdir(parents=True)  # no installed.json
    manager = ExtensionManager(extensions_dir, ModuleRegistry())
    assert manager.load_installed() == []


# --- HTTP surface ---


def _extension_client(config: ServerConfig) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app(config))
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )


@pytest.mark.anyio
async def test_extensions_disabled_without_dir(client: httpx.AsyncClient) -> None:
    listing = await client.get("/v1/extensions")
    assert listing.status_code == 200
    assert listing.json() == {"enabled": False, "extensions": []}
    install = await client.post("/v1/extensions", json={"path": "/nowhere"})
    assert install.status_code == 503


@pytest.mark.anyio
async def test_install_list_and_execute_over_http(tmp_path: Path) -> None:
    config = ServerConfig(
        token=TEST_TOKEN, token_explicit=True, extensions_dir=tmp_path / "extensions"
    )
    source = write_shout_extension(tmp_path)
    async with _extension_client(config) as client:
        installed = await client.post("/v1/extensions", json={"path": str(source)})
        assert installed.status_code == 201, installed.text
        assert installed.json() == {
            "name": "shout",
            "version": "0.1.0",
            "modules": ["text.shout"],
        }

        listing = await client.get("/v1/extensions")
        assert listing.json()["enabled"] is True
        assert [e["name"] for e in listing.json()["extensions"]] == ["shout"]

        modules = await client.get("/v1/modules")
        by_name = {m["name"]: m for m in modules.json()}
        assert by_name["text.shout"]["isolation"] == "isolated"

        session = (await client.post("/v1/sessions")).json()["id"]
        payload = await client.post(
            f"/v1/sessions/{session}/payloads",
            params={"type": "text/plain"},
            content=b"over http",
        )
        graph: dict[str, Any] = {
            "graph": {
                "nodes": [{"id": "s", "module": "text.shout", "params": {"exclaim": True}}],
                "bindings": [
                    {"payload": payload.json()["id"], "node": "s", "port": "text"}
                ],
                "outputs": [{"node": "s", "port": "text"}],
            }
        }
        job = await client.post(f"/v1/sessions/{session}/jobs", json=graph)
        assert job.status_code == 201, job.text

        result = await _wait_for_job(client, session, job.json()["id"])
        assert result["status"] == "completed"
        (output,) = result["outputs"]
        data = await client.get(f"/v1/sessions/{session}/payloads/{output['payload']}")
        assert data.content == b"OVER HTTP!"


@pytest.mark.anyio
async def test_install_conflict_over_http(tmp_path: Path) -> None:
    config = ServerConfig(
        token=TEST_TOKEN, token_explicit=True, extensions_dir=tmp_path / "extensions"
    )
    source = write_shout_extension(tmp_path)
    async with _extension_client(config) as client:
        first = await client.post("/v1/extensions", json={"path": str(source)})
        assert first.status_code == 201
        second = await client.post("/v1/extensions", json={"path": str(source)})
        assert second.status_code == 409


@pytest.mark.anyio
async def test_install_invalid_source_over_http(tmp_path: Path) -> None:
    config = ServerConfig(
        token=TEST_TOKEN, token_explicit=True, extensions_dir=tmp_path / "extensions"
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    async with _extension_client(config) as client:
        response = await client.post("/v1/extensions", json={"path": str(empty)})
        assert response.status_code == 422
        missing = await client.post("/v1/extensions", json={})
        assert missing.status_code == 400


async def _wait_for_job(
    client: httpx.AsyncClient, session: str, job: str, attempts: int = 200
) -> dict[str, Any]:
    for _ in range(attempts):
        state: dict[str, Any] = (await client.get(f"/v1/sessions/{session}/jobs/{job}")).json()
        if state["status"] in {"completed", "failed", "cancelled"}:
            return state
        await asyncio.sleep(0.05)
    raise AssertionError(f"job did not settle: {json.dumps(state)}")
