from __future__ import annotations

import os

import httpx

from benchmark.injectors.base import FaultInjector

FEATURE_WORKER_URL = os.environ.get("FEATURE_WORKER_URL", "http://localhost:8002")


class ConsumerLagInjector(FaultInjector):
    """Root cause: event-stream. See benchmark/scenarios/stream-lag-001.yaml."""

    fault_name = "consumer_lag"

    async def enable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{FEATURE_WORKER_URL}/admin/fault/lag", json={"enabled": True})

    async def disable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{FEATURE_WORKER_URL}/admin/fault/lag", json={"enabled": False})
