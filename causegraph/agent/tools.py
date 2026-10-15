"""Bounded evidence tools the investigator agent may call (spec section
6.1). "The agent should never receive the entire telemetry lake by
default" -- every method here enforces a hard cap (depth, time range,
row limit) regardless of what's asked for.

Two tools (`get_trace_summary`, `get_logs`) are honest stubs: Sprint 1 has
no queryable trace or log backend (traces go to the OTel Collector's debug
exporter, logs go to stdout -- see docs/adr/0002-telemetry-stack.md). They
return a clear "not available" result rather than fabricating data, per
the project's standing rule against inventing evidence.

`request_intervention_test` is benchmark/dev-mode only (spec section 6.1).
This module defines its bounded signature but never implements the real
fault-toggling itself -- that stays in benchmark/evaluator/
intervention_runner.py, which injects a callable here so causegraph/
never depends on benchmark/ (see causegraph/causal/intervention.py for the
same pattern). Absent an injected callable, it clearly reports itself as
unavailable rather than silently doing nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from causegraph.anomalies.prometheus_client import PrometheusClient
from causegraph.changes import ChangeEventRepository
from causegraph.graph.repository import Direction, GraphRepository
from causegraph.persistence import IncidentRepository

MAX_NEIGHBOR_DEPTH = 6
MAX_METRIC_WINDOW = timedelta(minutes=10)
MAX_CHANGE_LIMIT = 20
MAX_INCIDENT_HISTORY = 20
MAX_LOG_LIMIT = 100

InterventionTestFn = Callable[[str], dict]


@dataclass
class AgentTools:
    graph: GraphRepository
    change_repo: ChangeEventRepository = field(default_factory=ChangeEventRepository)
    incident_repo: IncidentRepository = field(default_factory=IncidentRepository)
    prometheus: PrometheusClient = field(default_factory=PrometheusClient)
    intervention_test_fn: InterventionTestFn | None = None  # injected by the benchmark harness only

    def get_dependency_neighbors(
        self, node_id: str, direction: str = "upstream", depth: int = 3
    ) -> list[dict]:
        depth = min(depth, MAX_NEIGHBOR_DEPTH)
        results = self.graph.neighbors(node_id, Direction(direction), depth)
        return [
            {"node_id": node.id, "type": node.type.value, "distance": d, "path": p}
            for node, d, p in results
        ]

    def get_metrics(
        self, node_id: str, metric_query: str, start: datetime, end: datetime
    ) -> dict:
        if end - start > MAX_METRIC_WINDOW:
            start = end - MAX_METRIC_WINDOW
        samples = self.prometheus.query_range(metric_query, start, end)
        return {"node_id": node_id, "query": metric_query, "sample_count": len(samples), "samples": samples}

    def get_trace_summary(self, service: str, start: datetime, end: datetime) -> dict:
        return {
            "service": service,
            "available": False,
            "note": "no queryable trace backend in this environment; see docs/adr/0002-telemetry-stack.md",
        }

    def get_recent_changes(self, node_id: str, start: datetime, end: datetime, limit: int = 10) -> list[dict]:
        changes = self.change_repo.recent_for_node(node_id, start, end)[: min(limit, MAX_CHANGE_LIMIT)]
        return [c.model_dump(mode="json") for c in changes]

    def get_logs(self, node_id: str, query: str, start: datetime, end: datetime, limit: int = 50) -> dict:
        return {
            "node_id": node_id,
            "query": query,
            "available": False,
            "lines": [],
            "note": "no centralized log store in this environment; see docs/adr/0002-telemetry-stack.md",
        }

    def get_incident_history(self, signature: str, k: int = 5) -> list[dict]:
        incidents = self.incident_repo.recent_by_trigger_signal(signature, min(k, MAX_INCIDENT_HISTORY))
        return [i.model_dump(mode="json") for i in incidents]

    def request_intervention_test(self, candidate_id: str) -> dict:
        if self.intervention_test_fn is None:
            return {
                "candidate_id": candidate_id,
                "available": False,
                "note": "intervention testing is benchmark/dev-mode only and was not enabled for this run",
            }
        return self.intervention_test_fn(candidate_id)
