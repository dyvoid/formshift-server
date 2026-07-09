"""First out-of-core extension end to end (M3): background removal.

Installs ``extensions/background-removal`` — a real pip resolve of rembg and
onnxruntime into the extension's venv, plus a model download on first run —
so this is gated like the other network e2e test.

Run with: FORMSHIFT_TEST_NETWORK=1 uv run pytest tests/test_removebg_e2e.py
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from formshift_server.app import create_app
from formshift_server.config import ServerConfig

from .conftest import TEST_TOKEN
from .test_extensions import _wait_for_job

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("FORMSHIFT_TEST_NETWORK") != "1",
        reason="downloads rembg + model weights; set FORMSHIFT_TEST_NETWORK=1 to run",
    ),
]

EXTENSION_SOURCE = Path(__file__).parent.parent / "extensions" / "background-removal"


def _photo_like_subject() -> bytes:
    """A large soft-edged dark disc on a light ground — salient enough for U^2-Net."""
    image = Image.new("RGB", (320, 320), (240, 240, 235))
    draw = ImageDraw.Draw(image)
    draw.ellipse((80, 80, 240, 240), fill=(60, 40, 35))
    draw.ellipse((110, 110, 170, 170), fill=(120, 90, 70))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


async def test_background_removal_extension_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep model weights out of the developer's real cache; the runner
    # subprocess inherits this environment.
    monkeypatch.setenv("U2NET_HOME", str(tmp_path / "models"))

    config = ServerConfig(
        token=TEST_TOKEN, token_explicit=True, extensions_dir=tmp_path / "extensions"
    )
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        timeout=1200,
    ) as client:
        installed = await client.post(
            "/v1/extensions", json={"path": str(EXTENSION_SOURCE)}
        )
        assert installed.status_code == 201, installed.text
        assert installed.json()["modules"] == ["image.removebg"]

        session = (await client.post("/v1/sessions")).json()["id"]
        payload = await client.post(
            f"/v1/sessions/{session}/payloads",
            params={"type": "raster/png"},
            content=_photo_like_subject(),
        )
        job = await client.post(
            f"/v1/sessions/{session}/jobs",
            json={
                "graph": {
                    "nodes": [{"id": "bg", "module": "image.removebg", "params": {}}],
                    "bindings": [
                        {"payload": payload.json()["id"], "node": "bg", "port": "image"}
                    ],
                    "outputs": [{"node": "bg", "port": "image"}],
                }
            },
        )
        assert job.status_code == 201, job.text
        result = await _wait_for_job(client, session, job.json()["id"], attempts=4800)
        assert result["status"] == "completed", result

        (output,) = result["outputs"]
        data = await client.get(f"/v1/sessions/{session}/payloads/{output['payload']}")
        cut = Image.open(io.BytesIO(data.content))
        assert cut.size == (320, 320)
        assert "A" in cut.getbands()
        alpha = cut.getchannel("A")
        # Background gone, subject kept: corners transparent, disc center opaque.
        for corner in [(4, 4), (315, 4), (4, 315), (315, 315)]:
            value = alpha.getpixel(corner)
            assert isinstance(value, int) and value < 32, f"corner {corner} still opaque: {value}"
        center = alpha.getpixel((160, 160))
        assert isinstance(center, int) and center > 224, f"subject center lost: {center}"
