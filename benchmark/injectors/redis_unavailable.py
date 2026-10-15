from __future__ import annotations

import os

import httpx

from benchmark.injectors.base import FaultInjector

MODEL_SERVICE_URL = os.environ.get("MODEL_SERVICE_URL", "http://localhost:8003")


class RedisUnavailableInjector(FaultInjector):
    """Root cause: feature-store. See
    benchmark/scenarios/redis-unavailable-001.yaml."""

    fault_name = "redis_unavailable"

    async def enable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{MODEL_SERVICE_URL}/admin/fault/redis-unavailable", json={"enabled": True}
            )

    async def disable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{MODEL_SERVICE_URL}/admin/fault/redis-unavailable", json={"enabled": False}
            )
