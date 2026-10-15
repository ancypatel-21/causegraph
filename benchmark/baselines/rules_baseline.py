"""B1: hand-authored rules baseline (spec section 9.1): "Fast and
deterministic. Brittle; poor coverage for novel multi-service incidents."

Deliberately a fixed signature table over *raw* signal thresholds (not the
scenario's fault label) -- a real rules engine only sees telemetry, not
ground truth. This is exactly why it's brittle: it only recognizes the
specific signal thresholds it was hand-tuned for, and a novel fault that
doesn't trip one of these exact thresholds falls through to a naive
fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from causegraph.anomalies.prometheus_client import PrometheusClient
from causegraph.graph.repository import GraphRepository
from causegraph.graph.topology import EVENT_API, EVENT_STREAM, FEATURE_WORKER, MODEL_SERVICE, RANKING_API
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.schemas import Hypothesis, Incident


@dataclass(frozen=True)
class Rule:
    node_id: str
    threshold: float


# Priority order matters: checked top to bottom, first match wins. A real
# root cause (e.g. model-service latency) is checked before a node that
# would merely *reflect* it (ranking-api's latency also rises when
# model-service is slow, since ranking-api awaits its response).
RULES: list[Rule] = [
    Rule(FEATURE_WORKER, threshold=0.3),
    Rule(MODEL_SERVICE, threshold=400.0),
    Rule(EVENT_STREAM, threshold=20.0),
    Rule(EVENT_API, threshold=0.3),
    Rule(RANKING_API, threshold=400.0),
]


class RulesBaseline:
    method_name = "rules"

    def __init__(self, graph: GraphRepository, prometheus: PrometheusClient | None = None) -> None:
        self.graph = graph
        self.prometheus = prometheus or PrometheusClient()

    def investigate(
        self,
        incident: Incident,
        incident_window=None,  # unused: this baseline checks only the latest instantaneous value
        top_k: int = 5,
    ) -> tuple[list[Hypothesis], list]:
        matched_node: str | None = None
        for rule in RULES:
            signal = NODE_SIGNALS.get(rule.node_id)
            if signal is None:
                continue
            value = self.prometheus.query(signal.query)
            if value is None:
                continue
            tripped = value > rule.threshold if signal.direction == "spike" else value < rule.threshold
            if tripped:
                matched_node = rule.node_id
                break

        if matched_node is not None:
            ordered = [matched_node] + [n.id for n in self.graph.all_nodes() if n.id != matched_node]
        else:
            # No known signature tripped: a rules engine with no matching
            # rule has nothing better than "wherever the alert fired."
            ordered = list(incident.symptom_nodes) + [
                n.id for n in self.graph.all_nodes() if n.id not in incident.symptom_nodes
            ]

        hypotheses = [
            Hypothesis(
                incident_id=incident.id,
                candidate_node=node_id,
                rank=rank,
                score=1.0 if matched_node == node_id else 0.0,
                score_components={"rule_matched": 1.0 if matched_node == node_id else 0.0},
                causal_path=[node_id],
                evidence_ids=[],
                contradicting_evidence_ids=[],
            )
            for rank, node_id in enumerate(ordered[:top_k], start=1)
        ]
        return hypotheses, []
