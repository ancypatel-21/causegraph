"""model-service: scores items using features from the feature-store. Owns
the `latency` fault used by scenario ml-latency-001. See
docs/adr/0001-service-boundaries.md.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import redis.asyncio as redis
from fastapi import FastAPI
from pydantic import BaseModel

from causegraph.changes.client import record_change_event
from causegraph.telemetry import get_logger, instrument_app
from causegraph.telemetry.metrics import ServiceMetrics, mount_metrics

SERVICE_NAME = "model-service"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CAUSEGRAPH_API_URL = os.environ.get("CAUSEGRAPH_API_URL", "http://localhost:8000")
MODEL_VERSION = "ranking-model-v1"

logger = get_logger(SERVICE_NAME)
metrics = ServiceMetrics(SERVICE_NAME)


@dataclass
class FaultState:
    latency_enabled: bool = False
    latency_ms: float = 500.0


fault_state = FaultState()
redis_client: redis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    logger.info("model-service started")
    try:
        yield
    finally:
        await redis_client.close()


app = FastAPI(title="model-service", lifespan=lifespan)
instrument_app(app, SERVICE_NAME)
mount_metrics(app, metrics)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _deterministic_noise(item_id: str) -> float:
    digest = hashlib.sha256(item_id.encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 1000) / 1000.0 * 0.1


@app.get("/predict")
async def predict(item_id: str) -> dict:
    start = time.perf_counter()

    if fault_state.latency_enabled:
        await asyncio.sleep(fault_state.latency_ms / 1000.0)

    feature_raw = await redis_client.get(f"feature:{item_id}") if redis_client else None
    feature = json.loads(feature_raw) if feature_raw else None

    if feature is None or feature.get("null"):
        score = 0.05 + _deterministic_noise(item_id)
        feature_skew = True
    else:
        score = math.log1p(feature.get("count", 0)) + _deterministic_noise(item_id)
        feature_skew = False

    duration_ms = (time.perf_counter() - start) * 1000.0
    metrics.set_signal("latency_ms", duration_ms)

    return {
        "item_id": item_id,
        "score": score,
        "model_version": MODEL_VERSION,
        "feature_skew": feature_skew,
    }


class LatencyFaultRequest(BaseModel):
    enabled: bool
    latency_ms: float = 500.0


@app.post("/admin/fault/latency")
async def set_latency_fault(payload: LatencyFaultRequest) -> dict:
    fault_state.latency_enabled = payload.enabled
    fault_state.latency_ms = payload.latency_ms
    await record_change_event(
        CAUSEGRAPH_API_URL,
        node_id=SERVICE_NAME,
        change_type="config",
        metadata={"fault": "latency", "enabled": payload.enabled, "latency_ms": payload.latency_ms},
    )
    logger.info(f"latency fault set to {payload.enabled} ({payload.latency_ms}ms)")
    return {"latency_enabled": fault_state.latency_enabled, "latency_ms": fault_state.latency_ms}
