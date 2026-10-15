from datetime import datetime

from causegraph.anomalies.detector import AnomalyResult
from causegraph.graph import build_reference_topology
from causegraph.graph.topology import FEATURE_WORKER, MODEL_SERVICE, QUALITY_MONITOR, RANKING_API
from causegraph.rca.graph_only import GraphOnlyBaseline
from causegraph.schemas import Incident


class FakeDetector:
    def __init__(self, severities: dict[str, float]) -> None:
        self.severities = severities

    def score(self, node_id, metric_query, incident_start, incident_end, direction="spike"):
        severity = self.severities.get(node_id, 0.0)
        return AnomalyResult(
            node_id=node_id,
            metric_query=metric_query,
            severity=severity,
            baseline_median=1.0,
            incident_value=1.0 + severity,
            has_data=node_id in self.severities,
        )


def _incident(symptom_nodes: list[str]) -> Incident:
    return Incident(
        started_at=datetime(2026, 1, 1), symptom_nodes=symptom_nodes, trigger_signal="test"
    )


def test_strong_upstream_anomaly_outranks_weak_symptom_anomaly():
    graph = build_reference_topology()
    # feature-worker has a much stronger anomaly than the symptom nodes
    # themselves, so it should still win on score despite being farther away.
    detector = FakeDetector({FEATURE_WORKER: 20.0, MODEL_SERVICE: 0.1, RANKING_API: 0.1})
    baseline = GraphOnlyBaseline(graph, detector=detector)

    incident = _incident([MODEL_SERVICE, RANKING_API])
    hypotheses, evidence = baseline.investigate(incident)

    assert hypotheses[0].candidate_node == FEATURE_WORKER
    assert hypotheses[0].rank == 1
    assert any(e.candidate_node == FEATURE_WORKER and e.supports for e in evidence)


def test_no_anomaly_data_yields_zero_score_but_no_crash():
    graph = build_reference_topology()
    detector = FakeDetector({})
    baseline = GraphOnlyBaseline(graph, detector=detector)

    incident = _incident([QUALITY_MONITOR])
    hypotheses, evidence = baseline.investigate(incident)

    assert all(h.score == 0.0 for h in hypotheses)
    assert evidence == []


def test_evidence_ids_are_attached_to_matching_hypothesis():
    graph = build_reference_topology()
    detector = FakeDetector({FEATURE_WORKER: 5.0})
    baseline = GraphOnlyBaseline(graph, detector=detector)

    incident = _incident([MODEL_SERVICE])
    hypotheses, evidence = baseline.investigate(incident)

    top = next(h for h in hypotheses if h.candidate_node == FEATURE_WORKER)
    evidence_ids = {e.id for e in evidence if e.candidate_node == FEATURE_WORKER}
    assert set(top.evidence_ids) == evidence_ids
    assert len(evidence_ids) > 0
