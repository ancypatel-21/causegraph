"""Deterministic seeded workload generator (spec section 7.1). Drives the
"User Events -> Kafka" side of the dependency chain; quality-monitor
independently drives traffic to ranking-api, so together the full chain
stays warm for the duration of a benchmark run.
"""

from __future__ import annotations

import asyncio
import os
import random

import httpx

from causegraph.telemetry import get_logger

logger = get_logger("workload-generator")

ITEM_POOL = [f"item-{i}" for i in range(20)]
USER_POOL = [f"user-{i}" for i in range(50)]


async def run_workload(
    seed: int,
    event_api_url: str,
    stop_event: asyncio.Event,
    events_per_second: float = 10.0,
) -> None:
    rng = random.Random(seed)
    interval = 1.0 / events_per_second
    sent = 0

    async with httpx.AsyncClient(timeout=3.0) as client:
        while not stop_event.is_set():
            payload = {
                "user_id": rng.choice(USER_POOL),
                "item_id": rng.choice(ITEM_POOL),
                "event_type": "impression",
                "qty": 1,
            }
            try:
                await client.post(f"{event_api_url}/events", json=payload)
                sent += 1
            except Exception as exc:
                logger.info(f"workload event failed: {exc}")
            await asyncio.sleep(interval)

    logger.info(f"workload generator stopped after sending {sent} events")


async def run_workload_for(
    seed: int,
    event_api_url: str,
    duration_seconds: float,
    events_per_second: float = 10.0,
) -> None:
    stop_event = asyncio.Event()
    task = asyncio.create_task(run_workload(seed, event_api_url, stop_event, events_per_second))
    await asyncio.sleep(duration_seconds)
    stop_event.set()
    await task
