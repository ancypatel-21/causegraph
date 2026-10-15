"""quality-monitor: periodically probes ranking-api and computes a
synthetic quality-proxy metric. This is where symptoms are first observed,
mirroring the spec's problem statement: "recommendation quality falls, but
the ranking service is healthy." See docs/adr/0001-service-boundaries.md.
"""

from __future__ import annotations

import asyncio
import os
import random
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from causegraph.telemetry import get_logger, instrument_app
from causegraph.telemetry.metrics import ServiceMetrics, mount_metrics

SERVICE_NAME = "quality-monitor"
RANKING_API_URL = os.environ.get("RANKING_API_URL", "http://localhost:8004")
PROBE_INTERVAL_SECONDS = float(os.environ.get("QUALITY_MONITOR_INTERVAL_SECONDS", "3.0"))
PROBE_ITEM_POOL = [f"item-{i}" for i in range(20)]

logger = get_logger(SERVICE_NAME)
metrics = ServiceMetrics(SERVICE_NAME)
http_client: httpx.AsyncClient | None = None
_rng = random.Random(7)
latest_quality_proxy: float | None = None


async def _probe_once() -> None:
    assert http_client is not None
    candidates = ",".join(_rng.sample(PROBE_ITEM_POOL, 5))
    try:
        resp = await http_client.get(
            f"{RANKING_API_URL}/rank", params={"user_id": "quality-monitor", "candidates": candidates}
        )
        resp.raise_for_status()
        ranked = resp.json()["ranked_items"]
        top_scores = [item["score"] for item in ranked[:3]]
        quality_proxy = sum(top_scores) / len(top_scores) if top_scores else 0.0
    except Exception as exc:
        logger.info(f"quality probe failed: {exc}")
        quality_proxy = 0.0

    global latest_quality_proxy
    latest_quality_proxy = quality_proxy
    metrics.set_signal("quality_proxy_score", quality_proxy)


async def _probe_loop() -> None:
    while True:
        await _probe_once()
        await asyncio.sleep(PROBE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=5.0)
    task = asyncio.create_task(_probe_loop())
    logger.info("quality-monitor started")
    try:
        yield
    finally:
        task.cancel()
        await http_client.aclose()


app = FastAPI(title="quality-monitor", lifespan=lifespan)
instrument_app(app, SERVICE_NAME)
mount_metrics(app, metrics)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/quality")
def quality() -> dict:
    return {"quality_proxy_score": latest_quality_proxy}
