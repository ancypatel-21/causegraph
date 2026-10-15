from datetime import datetime

from causegraph.graph import build_reference_topology
from causegraph.graph.topology import EVENT_STREAM, FEATURE_WORKER, MODEL_SERVICE
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.schemas import Incident

from benchmark.baselines.random_baseline import RandomBaseline
from benchmark.baselines.rules_baseline import RulesBaseline


def _incident(symptom_nodes: list[str], incident_id: str = "inc-fixed") -> Incident:
    incident = Incident(
        started_at=datetime(2026, 1, 1), symptom_nodes=symptom_nodes, trigger_signal="test"
    )
    incident.id = incident_id
    return incident


def test_random_baseline_is_deterministic_given_same_incident_id():
    graph = build_reference_topology()
    baseline = RandomBaseline(graph)
    incident = _incident(["ranking-api"])

    hyps_a, _ = baseline.investigate(incident)
    hyps_b, _ = baseline.investigate(incident)

    assert [h.candidate_node for h in hyps_a] == [h.candidate_node for h in hyps_b]


def test_random_baseline_covers_all_graph_nodes_as_eligible():
    graph = build_reference_topology()
    baseline = RandomBaseline(graph)
    incident = _incident(["ranking-api"], incident_id="inc-cover")
    hyps, _ = baseline.investigate(incident, top_k=100)
    ranked = {h.candidate_node for h in hyps}
    assert ranked == {n.id for n in graph.all_nodes()}


class FakePrometheusClient:
    """Keyed by node id, not raw query string -- resolves which node a
    query belongs to via NODE_SIGNALS (exact match) rather than naive
    substring containment, which breaks now that feature-store's query
    string contains "model-service" as a substring (it's attributed to
    model-service's view of it -- see causegraph/rca/node_signals.py)."""

    def __init__(self, values: dict[str, float]) -> None:
        self.values = values
        self._query_to_node = {signal.query: node_id for node_id, signal in NODE_SIGNALS.items()}

    def query(self, promql: str) -> float | None:
        node_id = self._query_to_node.get(promql)
        return self.values.get(node_id) if node_id else None

    def query_range(self, *args, **kwargs):
        raise NotImplementedError


def test_rules_baseline_matches_first_tripped_rule_in_priority_order():
    graph = build_reference_topology()
    # Both feature-worker and model-service signals are "tripped," but
    # feature-worker is earlier in RULES, so it must win.
    prometheus = FakePrometheusClient({"feature-worker": 0.9, "model-service": 900.0})
    baseline = RulesBaseline(graph, prometheus=prometheus)
    incident = _incident(["ranking-api"])

    hyps, _ = baseline.investigate(incident)
    assert hyps[0].candidate_node == FEATURE_WORKER
    assert hyps[0].score == 1.0


def test_rules_baseline_matches_second_rule_when_first_is_not_tripped():
    graph = build_reference_topology()
    prometheus = FakePrometheusClient({"feature-worker": 0.01, "model-service": 900.0})
    baseline = RulesBaseline(graph, prometheus=prometheus)
    incident = _incident(["ranking-api"])

    hyps, _ = baseline.investigate(incident)
    assert hyps[0].candidate_node == MODEL_SERVICE


def test_rules_baseline_falls_back_to_symptom_nodes_when_nothing_trips():
    graph = build_reference_topology()
    prometheus = FakePrometheusClient({})
    baseline = RulesBaseline(graph, prometheus=prometheus)
    incident = _incident([EVENT_STREAM])

    hyps, _ = baseline.investigate(incident)
    assert hyps[0].candidate_node == EVENT_STREAM
    assert hyps[0].score == 0.0
