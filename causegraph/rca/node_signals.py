"""Maps a graph node to the Prometheus query that carries its health signal.

Sprint 1 only wires up signals for nodes that a real service emits telemetry
for. Infrastructure nodes without their own process (feature-store,
engagement-feature, ranking-model, ranking-model-v1) have no entry and are
scored as "no data" by the anomaly detector -- they can still be traversed
as part of a causal path, they just never win on anomaly evidence alone
until later phases add richer signals for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from causegraph.graph import topology as t


@dataclass(frozen=True)
class NodeSignal:
    query: str
    direction: Literal["spike", "drop"]
    evidence_type: str


def _domain(service: str, signal: str) -> str:
    return f'causegraph_domain_signal{{service="{service}",signal="{signal}"}}'


NODE_SIGNALS: dict[str, NodeSignal] = {
    t.EVENT_API: NodeSignal(_domain("event-api", "error_rate"), "spike", "request_error_rate"),
    t.FEATURE_WORKER: NodeSignal(
        _domain("feature-worker", "null_feature_rate"), "spike", "feature_null_rate"
    ),
    t.EVENT_STREAM: NodeSignal(
        _domain("feature-worker", "consumer_lag_messages"), "spike", "consumer_lag"
    ),
    t.MODEL_SERVICE: NodeSignal(
        _domain("model-service", "latency_ms"), "spike", "latency_anomaly"
    ),
    t.RANKING_API: NodeSignal(
        _domain("ranking-api", "latency_ms"), "spike", "latency_anomaly"
    ),
    t.QUALITY_MONITOR: NodeSignal(
        _domain("quality-monitor", "quality_proxy_score"), "drop", "quality_drop"
    ),
}
