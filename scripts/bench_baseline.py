"""Performance baseline benchmark (M1 exit condition).

Spawns a real server subprocess, drives it over HTTP exactly like a client
would, and prints a markdown table for docs/performance-baseline.md.

Run: uv run python scripts/bench_baseline.py
"""

from __future__ import annotations

import io
import platform
import statistics
import subprocess
import sys
import threading
import time
from typing import Any

import httpx
from PIL import Image, ImageDraw

TOKEN = "bench-token"
REPEATS = 7


def make_design(width: int, height: int) -> bytes:
    """A synthetic but structured design: shapes and stripes, not a flat fill."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    step = max(20, width // 20)
    for i, x in enumerate(range(0, width, step)):
        if i % 2 == 0:
            draw.rectangle([x, 0, x + step // 2, height // 3], fill="black")
    draw.ellipse([width // 4, height // 3, 3 * width // 4, height - 10], fill="black")
    draw.ellipse(
        [width // 4 + step, height // 3 + step, 3 * width // 4 - step, height - 10 - step],
        fill="white",
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def start_server(extra_args: list[str] | None = None) -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(
        [sys.executable, "-m", "formshift_server.cli", "--port", "0", "--token", TOKEN]
        + (extra_args or []),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None
    base_url = ""
    deadline = time.time() + 15
    while time.time() < deadline:
        line = process.stdout.readline()
        if "listening on" in line:
            base_url = line.strip().rsplit(" ", 1)[-1]
        if "Application startup complete" in line:
            break
    if not base_url:
        process.kill()
        raise RuntimeError("server did not start")

    # Keep draining stdout: access logs would otherwise fill the pipe buffer
    # and block the server mid-benchmark.
    def drain() -> None:
        assert process.stdout is not None
        for _ in process.stdout:
            pass

    threading.Thread(target=drain, daemon=True).start()
    return process, base_url


def timed_job(
    client: httpx.Client, session_id: str, graph: dict[str, Any], draft: bool = False
) -> float:
    """Submit a job and poll to completion; returns wall seconds."""
    start = time.perf_counter()
    job_id = client.post(
        f"/v1/sessions/{session_id}/jobs", json={"graph": graph, "draft": draft}
    ).json()["id"]
    while True:
        doc = client.get(f"/v1/sessions/{session_id}/jobs/{job_id}").json()
        if doc["status"] in {"completed", "failed", "cancelled"}:
            assert doc["status"] == "completed", doc
            return time.perf_counter() - start
        time.sleep(0.002)


def median_of(runs: list[float]) -> str:
    return f"{statistics.median(runs) * 1000:.1f} ms"


def bench(client: httpx.Client) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []

    def upload(session_id: str, data: bytes) -> str:
        response = client.post(
            f"/v1/sessions/{session_id}/payloads",
            params={"type": "raster/png"},
            content=data,
        )
        return str(response.json()["id"])

    def trace_graph(payload_id: str, node_id: str = "t") -> dict[str, Any]:
        return {
            "nodes": [{"id": node_id, "module": "potrace.trace", "params": {"blacklevel": 0.5}}],
            "bindings": [{"payload": payload_id, "node": node_id, "port": "image"}],
            "outputs": [{"node": node_id, "port": "svg"}],
        }

    # --- Trace time, small and large ---
    for label, size in [("small 400x300", (400, 300)), ("large 3000x2250", (3000, 2250))]:
        session_id = client.post("/v1/sessions").json()["id"]
        payload_id = upload(session_id, make_design(*size))
        runs = []
        for i in range(REPEATS):
            graph = trace_graph(payload_id)
            graph["nodes"][0]["params"]["turdsize"] = 2 + i  # defeat the cache
            runs.append(timed_job(client, session_id, graph))
        rows.append((f"trace, {label} (cold)", median_of(runs)))

    # --- Cache-hit latency: identical job resubmitted ---
    session_id = client.post("/v1/sessions").json()["id"]
    payload_id = upload(session_id, make_design(400, 300))
    graph = trace_graph(payload_id)
    timed_job(client, session_id, graph)  # warm
    runs = [timed_job(client, session_id, graph) for _ in range(REPEATS)]
    rows.append(("trace, small (fully cached rerun)", median_of(runs)))

    # --- Per-edge cost: 1 vs 6 chained levels nodes on a 3000x2250 image ---
    session_id = client.post("/v1/sessions").json()["id"]
    payload_id = upload(session_id, make_design(3000, 2250))

    def chain(n: int, salt: int) -> dict[str, Any]:
        nodes = [
            {"id": f"lv{i}", "module": "image.levels", "params": {"black": salt + i, "white": 255}}
            for i in range(n)
        ]
        edges = [
            {
                "from_node": f"lv{i}",
                "from_port": "image",
                "to_node": f"lv{i + 1}",
                "to_port": "image",
            }
            for i in range(n - 1)
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "bindings": [{"payload": payload_id, "node": "lv0", "port": "image"}],
            "outputs": [{"node": f"lv{n - 1}", "port": "image"}],
        }

    one = [timed_job(client, session_id, chain(1, 10 + i)) for i in range(REPEATS)]
    six = [timed_job(client, session_id, chain(6, 40 + i)) for i in range(REPEATS)]
    per_edge = (statistics.median(six) - statistics.median(one)) / 5
    rows.append(("levels x1, 3000x2250 (cold)", median_of(one)))
    rows.append(("levels x6 chained, 3000x2250 (cold)", median_of(six)))
    rows.append(("per added node (in-process tier)", f"{per_edge * 1000:.1f} ms"))

    # --- Draft speedup: downsample(512) -> trace on the large design ---
    session_id = client.post("/v1/sessions").json()["id"]
    payload_id = upload(session_id, make_design(3000, 2250))

    def draft_chain(salt: int) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": "ds", "module": "image.downsample", "params": {"max_dimension": 512}},
                {
                    "id": "t",
                    "module": "potrace.trace",
                    "params": {"blacklevel": 0.5, "turdsize": salt},
                },
            ],
            "edges": [
                {"from_node": "ds", "from_port": "image", "to_node": "t", "to_port": "image"}
            ],
            "bindings": [{"payload": payload_id, "node": "ds", "port": "image"}],
            "outputs": [{"node": "t", "port": "svg"}],
        }

    full = [timed_job(client, session_id, draft_chain(2 + i), draft=False) for i in range(REPEATS)]
    draft = [timed_job(client, session_id, draft_chain(20 + i), draft=True) for i in range(REPEATS)]
    rows.append(("downsample->trace, 3000x2250, full quality (cold)", median_of(full)))
    rows.append(("downsample->trace, 3000x2250, draft@512 (cold)", median_of(draft)))
    rows.append(("draft speedup", f"{statistics.median(full) / statistics.median(draft):.1f}x"))

    return rows


def main() -> None:
    process, base_url = start_server()
    try:
        with httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=120,
        ) as client:
            rows = bench(client)
    finally:
        process.kill()

    print(f"\nplatform: {platform.platform()}, python {platform.python_version()}")
    print(f"cpu: {platform.processor()}")
    print(f"repeats: {REPEATS} (medians)\n")
    print("| Measurement | Median |")
    print("|---|---|")
    for label, value in rows:
        print(f"| {label} | {value} |")


if __name__ == "__main__":
    main()
