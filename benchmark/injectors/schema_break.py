from __future__ import annotations

import os

import httpx

from benchmark.injectors.base import FaultInjector

FEATURE_WORKER_URL = os.environ.get("FEATURE_WORKER_URL", "http://localhost:8002")


class SchemaBreakInjector(FaultInjector):
    """Root cause: feature-worker. See benchmark/scenarios/data-schema-001.yaml."""

    fault_name = "incompatible_schema"

    async def enable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{FEATURE_WORKER_URL}/admin/fault/schema", json={"enabled": True})

    async def disable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{FEATURE_WORKER_URL}/admin/fault/schema", json={"enabled": False})
