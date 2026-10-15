"""event-api: accepts synthetic user interaction events and produces them to
Kafka. See docs/adr/0001-service-boundaries.md.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from causegraph.telemetry import get_logger, instrument_app
from causegraph.telemetry.metrics import ServiceMetrics, mount_metrics
from causegraph.telemetry.rolling import RollingRate

SERVICE_NAME = "event-api"
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC = os.environ.get("KAFKA_INTERACTION_TOPIC", "interaction-events")

logger = get_logger(SERVICE_NAME)
metrics = ServiceMetrics(SERVICE_NAME)
error_rate = RollingRate(window_seconds=30.0)

producer: AIOKafkaProducer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await producer.start()
    logger.info("event-api started")
    try:
        yield
    finally:
        await producer.stop()


app = FastAPI(title="event-api", lifespan=lifespan)
instrument_app(app, SERVICE_NAME)
mount_metrics(app, metrics)


class EventIn(BaseModel):
    user_id: str
    item_id: str
    event_type: str = "impression"
    qty: int = 1


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/events")
async def post_event(event: EventIn) -> dict[str, str]:
    if producer is None:
        raise HTTPException(status_code=503, detail="producer not ready")

    payload = {
        "user_id": event.user_id,
        "item_id": event.item_id,
        "event_type": event.event_type,
        "qty": event.qty,
        "ts": time.time(),
    }
    try:
        await producer.send_and_wait(TOPIC, json.dumps(payload).encode("utf-8"))
        error_rate.record(False)
    except Exception as exc:
        error_rate.record(True)
        metrics.set_signal("error_rate", error_rate.rate())
        raise HTTPException(status_code=502, detail="failed to publish event") from exc

    metrics.set_signal("error_rate", error_rate.rate())
    return {"status": "accepted"}
