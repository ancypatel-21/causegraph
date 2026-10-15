"""B3 baseline: "Rank anomalous upstream nodes using topology and temporal
features; no LLM." (spec section 9.1). This is the first RCA method Sprint 1
implements end-to-end (spec section 21, step 45).

Algorithm (spec section 5.1, restricted to topology + anomaly, no change
events, no intervention evidence -- those are reserved for the full
CauseGraph method in a later phase):

1. Start from the incident's symptom node(s).
2. Traverse upstream within a bounded depth to generate candidates.
3. Score each candidate by its own anomaly severity in the incident window,
   discounted by graph distance from the symptom.
4. Rank candidates; emit Evidence + Hypothesis rows so the result is fully
   auditable, per the evidence model (spec section 4.3).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from causegraph.anomalies import AnomalyResult, RobustZScoreDetector
from causegraph.graph.repository import GraphRepository
from causegraph.graph.traversal import collect_upstream_candidates
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.schemas import Evidence, Hypothesis, Incident

DEFAULT_TRAVERSAL_DEPTH = 6
DEFAULT_INCIDENT_WINDOW = timedelta(minutes=2)
ANOMALY_SUPPORT_THRESHOLD = 1.5  # robust z-score above this counts as supporting evidence


class GraphOnlyBaseline:
    method_name = "graph_only"

    def __init__(self, graph: GraphRepository, detector: RobustZScoreDetector | None = None) -> None:
        self.graph = graph
        self.detector = detector or RobustZScoreDetector()

    def investigate(
        self,
        incident: Incident,
        depth: int = DEFAULT_TRAVERSAL_DEPTH,
        incident_window: timedelta = DEFAULT_INCIDENT_WINDOW,
        top_k: int = 5,
    ) -> tuple[list[Hypothesis], list[Evidence]]:
        candidates = collect_upstream_candidates(self.graph, incident.symptom_nodes, depth)

        incident_start = incident.started_at
        incident_end = incident_start + incident_window

        evidence: list[Evidence] = []
        scored: list[tuple[str, float, dict[str, float], int, list[str]]] = []

        for node_id, (distance, path) in candidates.items():
            anomaly = self._score_node(node_id, incident_start, incident_end)
            severity = anomaly.severity if anomaly is not None else 0.0

            if anomaly is not None and anomaly.has_data:
                ev = Evidence(
                    incident_id=incident.id,
                    candidate_node=node_id,
                    evidence_type=NODE_SIGNALS[node_id].evidence_type,
                    source="prometheus",
                    observed_at=incident_end,
                    value={
                        "severity": anomaly.severity,
                        "baseline_median": anomaly.baseline_median,
                        "incident_value": anomaly.incident_value,
                        "query": anomaly.metric_query,
                    },
                    reliability=0.7,
                    supports=severity >= ANOMALY_SUPPORT_THRESHOLD,
                )
                evidence.append(ev)

            score = severity / (1 + distance)
            components = {"anomaly_severity": severity, "graph_distance": float(distance)}
            scored.append((node_id, score, components, distance, path))

        scored.sort(key=lambda row: row[1], reverse=True)

        evidence_by_node: dict[str, list[str]] = {}
        for ev in evidence:
            evidence_by_node.setdefault(ev.candidate_node, []).append(ev.id)

        hypotheses: list[Hypothesis] = []
        for rank, (node_id, score, components, _distance, path) in enumerate(scored[:top_k], start=1):
            hypotheses.append(
                Hypothesis(
                    incident_id=incident.id,
                    candidate_node=node_id,
                    rank=rank,
                    score=score,
                    score_components=components,
                    causal_path=list(reversed(path)),
                    evidence_ids=evidence_by_node.get(node_id, []),
                    contradicting_evidence_ids=[],
                )
            )

        return hypotheses, evidence

    def _score_node(
        self, node_id: str, incident_start: datetime, incident_end: datetime
    ) -> AnomalyResult | None:
        signal = NODE_SIGNALS.get(node_id)
        if signal is None:
            return None
        return self.detector.score(
            node_id,
            signal.query,
            incident_start,
            incident_end,
            direction=signal.direction,
        )
