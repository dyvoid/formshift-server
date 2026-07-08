"""Parallel tracing speedup benchmark (M2 exit condition).

Times a 16-color separation graph (posterize -> 16 x mask/trace/colorize ->
merge tree) against servers started with --workers 1 and with the default
worker count. Run: uv run python scripts/bench_parallel.py
"""

from __future__ import annotations

import io
import os
import statistics
import time
from typing import Any, cast

import httpx
from bench_baseline import TOKEN, start_server
from PIL import Image, ImageDraw

COLORS = 16
REPEATS = 5
SIZE = 1600


def multicolor_design() -> bytes:
    """16 distinct color regions with organic-ish shapes, worth tracing."""
    values = [10, 90, 170, 250]
    image = Image.new("RGB", (SIZE, SIZE), "white")
    draw = ImageDraw.Draw(image)
    cell = SIZE // 4
    for i in range(COLORS):
        row, col = divmod(i, 4)
        color = (values[row], values[col], 128 if i % 2 else 40)
        x0, y0 = col * cell, row * cell
        draw.ellipse([x0 + 8, y0 + 8, x0 + cell - 8, y0 + cell - 8], fill=color)
        draw.rectangle([x0 + cell // 3, y0 + cell // 3, x0 + cell // 2, y0 + cell // 2], fill=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_graph(payload_id: str, palette: dict[int, str], salt: int) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "post", "module": "image.posterize", "params": {"colors": COLORS}}
    ]
    edges: list[dict[str, str]] = []
    for index, fill in palette.items():
        nodes += [
            {"id": f"mask{index}", "module": "image.colormask", "params": {"index": index}},
            {
                "id": f"trace{index}",
                "module": "potrace.trace",
                "params": {"blacklevel": 0.5, "turdsize": salt},  # salt defeats the cache
            },
            {"id": f"color{index}", "module": "svg.colorize", "params": {"fill": fill}},
        ]
        edges += [
            {
                "from_node": "post",
                "from_port": "image",
                "to_node": f"mask{index}",
                "to_port": "image",
            },
            {
                "from_node": f"mask{index}",
                "from_port": "mask",
                "to_node": f"trace{index}",
                "to_port": "image",
            },
            {
                "from_node": f"trace{index}",
                "from_port": "svg",
                "to_node": f"color{index}",
                "to_port": "svg",
            },
        ]
    layer = [(f"color{i}", "svg") for i in palette]
    merges = 0
    while len(layer) > 1:
        nxt = []
        for i in range(0, len(layer) - 1, 2):
            node_id = f"merge{merges}"
            merges += 1
            nodes.append({"id": node_id, "module": "svg.merge", "params": {}})
            under_node, under_port = layer[i]
            over_node, over_port = layer[i + 1]
            edges += [
                {
                    "from_node": under_node,
                    "from_port": under_port,
                    "to_node": node_id,
                    "to_port": "under",
                },
                {
                    "from_node": over_node,
                    "from_port": over_port,
                    "to_node": node_id,
                    "to_port": "over",
                },
            ]
            nxt.append((node_id, "svg"))
        if len(layer) % 2:
            nxt.append(layer[-1])
        layer = nxt
    return {
        "nodes": nodes,
        "edges": edges,
        "bindings": [{"payload": payload_id, "node": "post", "port": "image"}],
        "outputs": [{"node": layer[0][0], "port": "svg"}],
    }


def timed_job(client: httpx.Client, session_id: str, graph: dict[str, Any]) -> float:
    start = time.perf_counter()
    job_id = client.post(f"/v1/sessions/{session_id}/jobs", json={"graph": graph}).json()["id"]
    while True:
        doc = client.get(f"/v1/sessions/{session_id}/jobs/{job_id}").json()
        if doc["status"] in {"completed", "failed", "cancelled"}:
            assert doc["status"] == "completed", doc
            return time.perf_counter() - start
        time.sleep(0.002)


def bench_with_workers(workers_args: list[str], design: bytes) -> float:
    process, base_url = start_server(workers_args)
    try:
        with httpx.Client(
            base_url=base_url, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=300
        ) as client:
            session_id = client.post("/v1/sessions").json()["id"]
            payload_id = client.post(
                f"/v1/sessions/{session_id}/payloads",
                params={"type": "raster/png"},
                content=design,
            ).json()["id"]

            # Palette discovery via a posterize-only job (client flow).
            post_graph = {
                "nodes": [
                    {"id": "post", "module": "image.posterize", "params": {"colors": COLORS}}
                ],
                "bindings": [{"payload": payload_id, "node": "post", "port": "image"}],
                "outputs": [{"node": "post", "port": "image"}],
            }
            job_id = client.post(
                f"/v1/sessions/{session_id}/jobs", json={"graph": post_graph}
            ).json()["id"]
            while True:
                doc = client.get(f"/v1/sessions/{session_id}/jobs/{job_id}").json()
                if doc["status"] == "completed":
                    break
                time.sleep(0.01)
            data = client.get(
                f"/v1/sessions/{session_id}/payloads/{doc['outputs'][0]['payload']}"
            ).content
            image = Image.open(io.BytesIO(data))
            raw: list[int] = image.getpalette() or []
            colors = cast(list[tuple[int, int]], image.getcolors(maxcolors=256) or [])
            used: list[int] = sorted(i for _, i in colors)
            palette = {
                i: "#{:02x}{:02x}{:02x}".format(*raw[i * 3 : i * 3 + 3]) for i in used[:COLORS]
            }

            runs = [
                timed_job(client, session_id, build_graph(payload_id, palette, 2 + n))
                for n in range(REPEATS)
            ]
            return statistics.median(runs)
    finally:
        process.kill()


def main() -> None:
    design = multicolor_design()
    sequential = bench_with_workers(["--workers", "1"], design)
    parallel = bench_with_workers([], design)
    cores = os.cpu_count()
    print(f"\n16-color separation, {SIZE}x{SIZE}, medians of {REPEATS} (cold)")
    print(f"cpu cores: {cores}\n")
    print("| Configuration | Median |")
    print("|---|---|")
    print(f"| workers=1 (sequential) | {sequential * 1000:.0f} ms |")
    print(f"| workers=default ({cores}) | {parallel * 1000:.0f} ms |")
    print(f"| speedup | {sequential / parallel:.2f}x |")


if __name__ == "__main__":
    main()
