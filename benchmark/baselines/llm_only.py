"""B2: LLM-only baseline (spec section 9.1): "Provide bounded raw incident
telemetry without dependency-graph candidate ranking." Every node that
emits telemetry is considered every time, with no topology-based
narrowing or distance hint -- the LLM gets raw signals and recent changes
and nothing else. Compare against B4 (graph narrows first) and CauseGraph
(graph + causal validation) to see what topology and causal evidence add.
"""

from __future__ import annotations

from datetime import timedelta

from causegraph.anomalies import RobustZScoreDetector
from causegraph.changes import ChangeEventRepository
from causegraph.llm import CandidateContext, LLMProvider, get_default_provider
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.schemas import Evidence, Hypothesis, Incident

DEFAULT_INCIDENT_WINDOW = timedelta(seconds=15)
CHANGE_LOOKBACK = timedelta(minutes=5)


class LlmOnlyBaseline:
    method_name = "llm_only"

    def __init__(
        self,
        detector: RobustZScoreDetector | None = None,
        change_repo: ChangeEventRepository | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self.detector = detector or RobustZScoreDetector()
        self.change_repo = change_repo or ChangeEventRepository()
        self.provider = provider or get_default_provider()

    def investigate(
        self,
        incident: Incident,
        incident_window: timedelta = DEFAULT_INCIDENT_WINDOW,
        top_k: int = 5,
    ) -> tuple[list[Hypothesis], list[Evidence]]:
        incident_start = incident.started_at
        incident_end = incident_start + incident_window

        candidates: list[CandidateContext] = []
        for node_id, signal in NODE_SIGNALS.items():
            anomaly = self.detector.score(
                node_id, signal.query, incident_start, incident_end, direction=signal.direction
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
                if anomaly.has_data
                else {}
            )
            candidates.append(
                CandidateContext(
                    node_id=node_id,
                    node_type="telemetry-emitting component",
                    raw_signals=raw_signals,
                    graph_distance=None,  # no topology given to this baseline, by design
                    recent_changes=[f"{c.type} at {c.timestamp.isoformat()}" for c in changes],
                )
            )

        summary = (
            f"trigger_signal={incident.trigger_signal}; "
            f"symptom_nodes={incident.symptom_nodes}"
        )
        result = self.provider.rank_candidates(summary, candidates)

        evidence: list[Evidence] = []
        for c in candidates:
            if not c.raw_signals:
                continue
            evidence.append(
                Evidence(
                    incident_id=incident.id,
                    candidate_node=c.node_id,
                    evidence_type="llm_raw_signal",
                    source=f"llm:{result.provider_name}/{result.model_name}",
                    observed_at=incident_end,
                    value={**c.raw_signals, "rationale": result.rationale.get(c.node_id, "")},
                    reliability=0.5,  # LLM judgment over raw telemetry, not a validated causal signal
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
                causal_path=[node_id],
                evidence_ids=evidence_by_node.get(node_id, []),
                contradicting_evidence_ids=[],
            )
            for rank, node_id in enumerate(result.ranked_node_ids[:top_k], start=1)
        ]
        return hypotheses, evidence
