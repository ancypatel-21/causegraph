"""HTTP client used by services/fault injectors to record a change event
against the central causegraph-api, instead of writing to Postgres directly
from every service process. See docs/adr/0002-telemetry-stack.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx


async def record_change_event(
    causegraph_api_url: str,
    node_id: str,
    change_type: str,
    *,
    version_before: str | None = None,
    version_after: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = {
        "node_id": node_id,
        "type": change_type,
        "version_before": version_before,
        "version_after": version_after,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(f"{causegraph_api_url}/changes", json=payload)
