"""Thin Prometheus HTTP API client. The anomaly engine's only data source,
per docs/adr/0002-telemetry-stack.md."""

from __future__ import annotations

import os
from datetime import datetime

import httpx


class PrometheusClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

    def query_range(
        self, promql: str, start: datetime, end: datetime, step_seconds: int = 5
    ) -> list[tuple[float, float]]:
        """Returns a list of (unix_timestamp, value) samples, empty on no data."""
        resp = httpx.get(
            f"{self.base_url}/api/v1/query_range",
            params={
                "query": promql,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step_seconds,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "success":
            return []

        result = payload["data"]["result"]
        if not result:
            return []

        samples: list[tuple[float, float]] = []
        for series in result:
            for ts, value in series["values"]:
                samples.append((float(ts), float(value)))
        samples.sort(key=lambda s: s[0])
        return samples

    def query(self, promql: str) -> float | None:
        resp = httpx.get(
            f"{self.base_url}/api/v1/query", params={"query": promql}, timeout=10.0
        )
        resp.raise_for_status()
        payload = resp.json()
        result = payload.get("data", {}).get("result", [])
        if not result:
            return None
        return float(result[0]["value"][1])
