"""M3 exit condition: an extension whose dependency pins would conflict with
core installs into isolation and works (design doc, Milestones).

The fixture extension pins ``pillow==10.4.0`` while core requires
``pillow>=11`` — the two could not share an environment. The test installs it
over the real HTTP API (venv creation plus a genuine pip download, hence the
network gate), then runs its module and checks the result was produced by the
pinned version, not core's.

Run with: FORMSHIFT_TEST_NETWORK=1 uv run pytest tests/test_extension_conflict_e2e.py
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import PIL
import pytest

from formshift_server.app import create_app
from formshift_server.config import ServerConfig

from .conftest import TEST_TOKEN
from .test_extensions import _wait_for_job

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("FORMSHIFT_TEST_NETWORK") != "1",
        reason="downloads packages from PyPI; set FORMSHIFT_TEST_NETWORK=1 to run",
    ),
]

PINNED_PILLOW = "10.4.0"

CONFLICT_MANIFEST = f"""\
[extension]
name = "pinned-invert"
version = "0.1.0"
description = "inverts an image with a Pillow pin that conflicts with core"
requirements = ["pillow=={PINNED_PILLOW}"]

[[modules]]
name = "image.pinned_invert"
description = "invert PNG, reporting the Pillow version that did it"
entry = "pinned_invert:run"
[[modules.inputs]]
name = "image"
type = "raster/png"
[[modules.outputs]]
name = "image"
type = "raster/png"
[[modules.outputs]]
name = "pillow_version"
type = "text/plain"
"""

CONFLICT_CODE = '''\
import io

import PIL
from PIL import Image, ImageOps


def run(inputs, params, draft):
    image = Image.open(io.BytesIO(inputs["image"])).convert("RGB")
    out = io.BytesIO()
    ImageOps.invert(image).save(out, format="PNG")
    return {
        "image": ("raster/png", out.getvalue()),
        "pillow_version": ("text/plain", PIL.__version__.encode()),
    }
'''


async def test_conflicting_pin_installs_isolated_and_works(tmp_path: Path) -> None:
    assert PIL.__version__ != PINNED_PILLOW, "core must actually conflict with the pin"

    source = tmp_path / "pinned-invert-src"
    source.mkdir()
    (source / "extension.toml").write_text(CONFLICT_MANIFEST, encoding="utf-8")
    (source / "pinned_invert.py").write_text(CONFLICT_CODE, encoding="utf-8")

    import io

    from PIL import Image

    png = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(png, format="PNG")

    config = ServerConfig(
        token=TEST_TOKEN, token_explicit=True, extensions_dir=tmp_path / "extensions"
    )
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        timeout=600,
    ) as client:
        installed = await client.post("/v1/extensions", json={"path": str(source)})
        assert installed.status_code == 201, installed.text

        session = (await client.post("/v1/sessions")).json()["id"]
        payload = await client.post(
            f"/v1/sessions/{session}/payloads",
            params={"type": "raster/png"},
            content=png.getvalue(),
        )
        job = await client.post(
            f"/v1/sessions/{session}/jobs",
            json={
                "graph": {
                    "nodes": [{"id": "inv", "module": "image.pinned_invert", "params": {}}],
                    "bindings": [
                        {"payload": payload.json()["id"], "node": "inv", "port": "image"}
                    ],
                    "outputs": [
                        {"node": "inv", "port": "image"},
                        {"node": "inv", "port": "pillow_version"},
                    ],
                }
            },
        )
        assert job.status_code == 201, job.text
        result = await _wait_for_job(client, session, job.json()["id"], attempts=2400)
        assert result["status"] == "completed", result

        outputs = {o["port"]: o["payload"] for o in result["outputs"]}
        version = await client.get(f"/v1/sessions/{session}/payloads/{outputs['pillow_version']}")
        assert version.content.decode() == PINNED_PILLOW  # the isolated venv's Pillow, not core's

        inverted = await client.get(f"/v1/sessions/{session}/payloads/{outputs['image']}")
        image = Image.open(io.BytesIO(inverted.content))
        assert image.getpixel((0, 0)) == (0, 255, 255)  # red inverted to cyan
