from __future__ import annotations

import os

import httpx

from benchmark.injectors.base import FaultInjector

FEATURE_WORKER_URL = os.environ.get("FEATURE_WORKER_URL", "http://localhost:8002")


class CacheTtlInjector(FaultInjector):
    """Root cause: feature-worker, but quietly -- it keeps writing valid
    data, only the TTL regresses. See benchmark/scenarios/cache-ttl-001.yaml.
    """

    fault_name = "cache_ttl_regression"

    async def enable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{FEATURE_WORKER_URL}/admin/fault/ttl", json={"enabled": True})

    async def disable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{FEATURE_WORKER_URL}/admin/fault/ttl", json={"enabled": False})
