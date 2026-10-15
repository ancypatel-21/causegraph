"""feature-worker: consumes interaction events, computes a feature per
item, and writes it to the feature-store (Redis). Owns the
`incompatible_schema` fault used by scenario data-schema-001. See
docs/adr/0001-service-boundaries.md and benchmark/scenarios/data-schema-001.yaml.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass

import redis.asyncio as redis
from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI
from pydantic import BaseModel

from causegraph.changes.client import record_change_event
from causegraph.telemetry import get_logger, instrument_app
from causegraph.telemetry.metrics import ServiceMetrics, mount_metrics
from causegraph.telemetry.rolling import RollingRate

SERVICE_NAME = "feature-worker"
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC = os.environ.get("KAFKA_INTERACTION_TOPIC", "interaction-events")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CAUSEGRAPH_API_URL = os.environ.get("CAUSEGRAPH_API_URL", "http://localhost:8000")
FEATURE_TTL_SECONDS = 300

logger = get_logger(SERVICE_NAME)
metrics = ServiceMetrics(SERVICE_NAME)
null_feature_rate = RollingRate(window_seconds=30.0)


@dataclass
class FaultState:
    schema_broken: bool = False
    lag_paused: bool = False


fault_state = FaultState()
redis_client: redis.Redis | None = None
_item_counts: dict[str, int] = {}
_consumer: AIOKafkaConsumer | None = None


async def _consume_loop() -> None:
    global _consumer
    _consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="feature-worker",
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )
    await _consumer.start()
    logger.info("feature-worker consumer started")
    try:
        while True:
            if fault_state.lag_paused:
                await asyncio.sleep(1.0)
                continue

            batch = await _consumer.getmany(timeout_ms=1000, max_records=50)
            for messages in batch.values():
                for message in messages:
                    await _process_message(message.value)
    finally:
        await _consumer.stop()


async def _process_message(raw: bytes) -> None:
    event = json.loads(raw.decode("utf-8"))
    item_id = event["item_id"]

    if fault_state.schema_broken:
        # Deliberately read a field that does not exist in the real event
        # schema, simulating an incompatible schema change at this
        # component. This is the root-cause fault for data-schema-001.
        qty = event.get("quantity")  # real field is "qty"
        is_null = qty is None
        null_feature_rate.record(is_null)
        feature_value = {"count": None, "recency_ts": None, "null": True}
    else:
        _item_counts[item_id] = _item_counts.get(item_id, 0) + event.get("qty", 1)
        null_feature_rate.record(False)
        feature_value = {
            "count": _item_counts[item_id],
            "recency_ts": event.get("ts"),
            "null": False,
        }

    metrics.set_signal("null_feature_rate", null_feature_rate.rate())

    if redis_client is not None:
        await redis_client.set(f"feature:{item_id}", json.dumps(feature_value), ex=FEATURE_TTL_SECONDS)


async def _lag_reporter_loop() -> None:
    while True:
        await asyncio.sleep(2.0)
        if _consumer is None:
            continue
        try:
            partitions = _consumer.assignment()
            if not partitions:
                continue
            total_lag = 0
            end_offsets = await _consumer.end_offsets(list(partitions))
            for tp in partitions:
                position = await _consumer.position(tp)
                total_lag += max(0, end_offsets[tp] - position)
            metrics.set_signal("consumer_lag_messages", float(total_lag))
        except Exception as exc:  # pragma: no cover - best-effort telemetry
            logger.info(f"lag reporter error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    consume_task = asyncio.create_task(_consume_loop())
    lag_task = asyncio.create_task(_lag_reporter_loop())
    try:
        yield
    finally:
        consume_task.cancel()
        lag_task.cancel()
        await redis_client.close()


app = FastAPI(title="feature-worker", lifespan=lifespan)
instrument_app(app, SERVICE_NAME)
mount_metrics(app, metrics)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


class SchemaFaultRequest(BaseModel):
    enabled: bool


@app.post("/admin/fault/schema")
async def set_schema_fault(payload: SchemaFaultRequest) -> dict[str, bool]:
    fault_state.schema_broken = payload.enabled
    await record_change_event(
        CAUSEGRAPH_API_URL,
        node_id=SERVICE_NAME,
        change_type="schema",
        version_before="v1" if payload.enabled else "v2",
        version_after="v2" if payload.enabled else "v1",
        metadata={"fault": "incompatible_schema", "enabled": payload.enabled},
    )
    logger.info(f"schema fault set to {payload.enabled}")
    return {"schema_broken": fault_state.schema_broken}


class LagFaultRequest(BaseModel):
    enabled: bool


@app.post("/admin/fault/lag")
async def set_lag_fault(payload: LagFaultRequest) -> dict[str, bool]:
    fault_state.lag_paused = payload.enabled
    await record_change_event(
        CAUSEGRAPH_API_URL,
        node_id="event-stream",
        change_type="config",
        metadata={"fault": "consumer_lag", "enabled": payload.enabled},
    )
    logger.info(f"lag fault set to {payload.enabled}")
    return {"lag_paused": fault_state.lag_paused}
