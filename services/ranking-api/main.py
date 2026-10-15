"""ranking-api: calls model-service for a candidate set and returns ranked
results. The client-facing entry point of the reference application. See
docs/adr/0001-service-boundaries.md.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from causegraph.telemetry import get_logger, instrument_app
from causegraph.telemetry.metrics import ServiceMetrics, mount_metrics
from causegraph.telemetry.rolling import RollingRate

SERVICE_NAME = "ranking-api"
MODEL_SERVICE_URL = os.environ.get("MODEL_SERVICE_URL", "http://localhost:8003")
REQUEST_TIMEOUT_SECONDS = 3.0

logger = get_logger(SERVICE_NAME)
metrics = ServiceMetrics(SERVICE_NAME)
error_rate = RollingRate(window_seconds=30.0)

http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    logger.info("ranking-api started")
    try:
        yield
    finally:
        await http_client.aclose()


app = FastAPI(title="ranking-api", lifespan=lifespan)
instrument_app(app, SERVICE_NAME)
mount_metrics(app, metrics)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _score_candidate(item_id: str) -> dict:
    assert http_client is not None
    try:
        resp = await http_client.get(f"{MODEL_SERVICE_URL}/predict", params={"item_id": item_id})
        resp.raise_for_status()
        error_rate.record(False)
        return resp.json()
    except Exception:
        error_rate.record(True)
        return {"item_id": item_id, "score": 0.0, "model_version": None, "feature_skew": True}


@app.get("/rank")
async def rank(user_id: str, candidates: str) -> dict:
    start = time.perf_counter()
    item_ids = [c.strip() for c in candidates.split(",") if c.strip()]

    results = await asyncio.gather(*[_score_candidate(item_id) for item_id in item_ids])
    ranked = sorted(results, key=lambda r: r["score"], reverse=True)

    duration_ms = (time.perf_counter() - start) * 1000.0
    metrics.set_signal("latency_ms", duration_ms)
    metrics.set_signal("error_rate", error_rate.rate())

    return {"user_id": user_id, "ranked_items": ranked}
