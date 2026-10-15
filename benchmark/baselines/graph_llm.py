"""B4: graph + LLM baseline (spec section 9.1): "Graph narrows candidates;
LLM synthesizes evidence, without CauseGraph causal validation." Same
upstream-traversal candidate set as the graph-only baseline (B3), but
ranking is delegated to the LLM provider instead of the fixed
severity/distance formula -- and unlike B2, each candidate carries its
real graph distance.
"""

from __future__ import annotations

from datetime import timedelta

from causegraph.anomalies import RobustZScoreDetector
from causegraph.changes import ChangeEventRepository
from causegraph.graph.repository import GraphRepository
from causegraph.graph.traversal import collect_upstream_candidates
from causegraph.llm import CandidateContext, LLMProvider, get_default_provider
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.schemas import Evidence, Hypothesis, Incident

DEFAULT_TRAVERSAL_DEPTH = 6
DEFAULT_INCIDENT_WINDOW = timedelta(seconds=15)
CHANGE_LOOKBACK = timedelta(minutes=5)


class GraphLlmBaseline:
    method_name = "graph_llm"

    def __init__(
        self,
        graph: GraphRepository,
        detector: RobustZScoreDetector | None = None,
        change_repo: ChangeEventRepository | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self.graph = graph
        self.detector = detector or RobustZScoreDetector()
        self.change_repo = change_repo or ChangeEventRepository()
        self.provider = provider or get_default_provider()

    def investigate(
        self,
        incident: Incident,
        depth: int = DEFAULT_TRAVERSAL_DEPTH,
        incident_window: timedelta = DEFAULT_INCIDENT_WINDOW,
        top_k: int = 5,
    ) -> tuple[list[Hypothesis], list[Evidence]]:
        candidate_paths = collect_upstream_candidates(self.graph, incident.symptom_nodes, depth)
        incident_start = incident.started_at
        incident_end = incident_start + incident_window

        contexts: list[CandidateContext] = []
        for node_id, (distance, _path) in candidate_paths.items():
            signal = NODE_SIGNALS.get(node_id)
            anomaly = (
                self.detector.score(
                    node_id, signal.query, incident_start, incident_end, direction=signal.direction
                )
                if signal
                else None
            )
            changes = self.change_repo.recent_for_node(
                node_id, incident_start - CHANGE_LOOKBACK, incident_end
            )
            raw_signals = (
                {
                    "observed_value": anomaly.incident_value,
                    "baseline_median": anomaly.baseline_median,
                    "severity_z": anomaly.severity,
                }
                if anomaly is not None and anomaly.has_data
                else {}
            )
            node = self.graph.get_node(node_id)
            contexts.append(
                CandidateContext(
                    node_id=node_id,
                    node_type=node.type.value if node else "unknown",
                    raw_signals=raw_signals,
                    graph_distance=distance,
                    recent_changes=[f"{c.type} at {c.timestamp.isoformat()}" for c in changes],
                )
            )

        summary = (
            f"trigger_signal={incident.trigger_signal}; symptom_nodes={incident.symptom_nodes}; "
            f"candidates narrowed by upstream graph traversal to depth {depth}"
        )
        result = self.provider.rank_candidates(summary, contexts)

        evidence: list[Evidence] = []
        for c in contexts:
            if not c.raw_signals:
                continue
            evidence.append(
                Evidence(
                    incident_id=incident.id,
                    candidate_node=c.node_id,
                    evidence_type="llm_graph_narrowed_signal",
                    source=f"llm:{result.provider_name}/{result.model_name}",
                    observed_at=incident_end,
                    value={**c.raw_signals, "rationale": result.rationale.get(c.node_id, "")},
                    reliability=0.6,  # graph narrowing gives this slightly more trust than B2
                    supports=result.ranked_node_ids[:1] == [c.node_id],
                )
            )

        evidence_by_node: dict[str, list[str]] = {}
        for ev in evidence:
            evidence_by_node.setdefault(ev.candidate_node, []).append(ev.id)

        hypotheses = [
            Hypothesis(
                incident_id=incident.id,
                candidate_node=node_id,
                rank=rank,
                score=max(0.0, result.confidence - 0.1 * (rank - 1)),
                score_components={"llm_confidence": result.confidence},
                causal_path=list(reversed(candidate_paths[node_id][1])),
                evidence_ids=evidence_by_node.get(node_id, []),
                contradicting_evidence_ids=[],
            )
            for rank, node_id in enumerate(result.ranked_node_ids[:top_k], start=1)
            if node_id in candidate_paths
        ]
        return hypotheses, evidence
