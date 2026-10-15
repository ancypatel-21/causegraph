from __future__ import annotations

import os

import httpx

from benchmark.injectors.base import FaultInjector

MODEL_SERVICE_URL = os.environ.get("MODEL_SERVICE_URL", "http://localhost:8003")


class LatencyInjector(FaultInjector):
    """Root cause: model-service. See benchmark/scenarios/ml-latency-001.yaml."""

    fault_name = "latency"

    def __init__(self, latency_ms: float = 600.0) -> None:
        self.latency_ms = latency_ms

    async def enable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{MODEL_SERVICE_URL}/admin/fault/latency",
                json={"enabled": True, "latency_ms": self.latency_ms},
            )

    async def disable(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{MODEL_SERVICE_URL}/admin/fault/latency", json={"enabled": False}
            )
