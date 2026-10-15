from datetime import datetime, timedelta

from causegraph.anomalies.detector import AnomalyResult
from causegraph.graph import build_reference_topology
from causegraph.graph.topology import FEATURE_WORKER, MODEL_SERVICE, QUALITY_MONITOR, RANKING_API
from causegraph.rca.causegraph_method import ALL_TERMS, CauseGraphMethod, DEFAULT_INCIDENT_WINDOW
from causegraph.schemas import ChangeEvent, Incident

INCIDENT_START = datetime(2026, 1, 1, 0, 0)
EARLY_END = INCIDENT_START + (DEFAULT_INCIDENT_WINDOW / 2)
FULL_END = INCIDENT_START + DEFAULT_INCIDENT_WINDOW


class FakeDetector:
    def __init__(self, full: dict[str, float], early: dict[str, float] | None = None) -> None:
        self.full = full
        self.early = early or full

    def score(self, node_id, metric_query, incident_start, incident_end, direction="spike"):
        table = self.early if incident_end == EARLY_END else self.full
        severity = table.get(node_id, 0.0)
        return AnomalyResult(
            node_id=node_id,
            metric_query=metric_query,
            severity=severity,
            baseline_median=1.0,
            incident_value=1.0 + severity,
            has_data=node_id in table,
        )


class FakeChangeRepo:
    def __init__(self, nodes_with_changes: set[str]) -> None:
        self.nodes_with_changes = nodes_with_changes

    def recent_for_node(self, node_id, start, end) -> list[ChangeEvent]:
        if node_id in self.nodes_with_changes:
            return [
                ChangeEvent(node_id=node_id, type="config", timestamp=start, metadata={})
            ]
        return []


def _incident(symptom_nodes: list[str]) -> Incident:
    return Incident(started_at=INCIDENT_START, symptom_nodes=symptom_nodes, trigger_signal="test")


def test_strong_consistent_upstream_cause_outranks_symptom():
    graph = build_reference_topology()
    detector = FakeDetector(
        full={FEATURE_WORKER: 8.0, MODEL_SERVICE: 2.0, RANKING_API: 0.1, QUALITY_MONITOR: 0.1},
        early={FEATURE_WORKER: 8.0, MODEL_SERVICE: 0.1, RANKING_API: 0.0, QUALITY_MONITOR: 0.0},
    )
    change_repo = FakeChangeRepo(nodes_with_changes={FEATURE_WORKER})
    method = CauseGraphMethod(graph, detector=detector, change_repo=change_repo)

    incident = _incident([MODEL_SERVICE, RANKING_API])
    hypotheses, evidence = method.investigate(incident)

    assert hypotheses[0].candidate_node == FEATURE_WORKER
    assert hypotheses[0].score_components.keys() == ALL_TERMS
    assert any(e.candidate_node == FEATURE_WORKER for e in evidence)


def test_ablation_drops_the_disabled_term_from_score_components():
    graph = build_reference_topology()
    detector = FakeDetector(full={FEATURE_WORKER: 5.0})
    change_repo = FakeChangeRepo(nodes_with_changes={FEATURE_WORKER})
    ablated_terms = ALL_TERMS - {"C"}
    method = CauseGraphMethod(
        graph, detector=detector, change_repo=change_repo, enabled_terms=ablated_terms
    )

    incident = _incident([MODEL_SERVICE])
    hypotheses, _ = method.investigate(incident)

    top = next(h for h in hypotheses if h.candidate_node == FEATURE_WORKER)
    assert "C" not in top.score_components
    assert top.score_components.keys() == ablated_terms


def test_intervention_evidence_can_promote_a_quiet_candidate():
    graph = build_reference_topology()
    detector = FakeDetector(full={})  # nothing anomalous anywhere

    def intervention_scorer(node_id: str, incident: Incident) -> float:
        return 1.0 if node_id == MODEL_SERVICE else 0.0

    method = CauseGraphMethod(
        graph,
        detector=detector,
        change_repo=FakeChangeRepo(nodes_with_changes=set()),
        intervention_scorer=intervention_scorer,
    )
    incident = _incident([RANKING_API])
    hypotheses, _ = method.investigate(incident)

    assert hypotheses[0].candidate_node == MODEL_SERVICE
    assert hypotheses[0].score_components["I"] == 1.0


def test_quiet_candidate_gets_contradicting_evidence_penalty():
    graph = build_reference_topology()
    # model-service is a candidate with telemetry but shows no anomaly at
    # all -- a healthy control, which should count against it (X term).
    detector = FakeDetector(full={MODEL_SERVICE: 0.0})
    method = CauseGraphMethod(
        graph, detector=detector, change_repo=FakeChangeRepo(nodes_with_changes=set())
    )

    incident = _incident([RANKING_API])
    # top_k=20 so the quiet candidate (correctly ranked low by the X
    # penalty) is still present to inspect its score_components.
    hypotheses, _ = method.investigate(incident, top_k=20)

    top = next(h for h in hypotheses if h.candidate_node == MODEL_SERVICE)
    assert top.score_components["X"] == 1.0
    assert top.score < 0  # the penalty should make it rank below a no-evidence node
