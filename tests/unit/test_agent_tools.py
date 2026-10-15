from datetime import datetime

from causegraph.agent.tools import MAX_NEIGHBOR_DEPTH, AgentTools
from causegraph.graph import build_reference_topology
from causegraph.graph.topology import QUALITY_MONITOR


class FakeChangeRepo:
    def recent_for_node(self, node_id, start, end):
        return []


class FakeIncidentRepo:
    def recent_by_trigger_signal(self, signature, k):
        self.last_k = k
        return []


def test_get_dependency_neighbors_caps_depth_at_max():
    graph = build_reference_topology()
    tools = AgentTools(graph=graph, change_repo=FakeChangeRepo(), incident_repo=FakeIncidentRepo())

    captured_depth = {}
    real_neighbors = graph.neighbors

    def spy_neighbors(node_id, direction, depth):
        captured_depth["depth"] = depth
        return real_neighbors(node_id, direction, depth)

    graph.neighbors = spy_neighbors

    tools.get_dependency_neighbors(QUALITY_MONITOR, direction="upstream", depth=999)
    # The requested depth (999) must never reach the graph unbounded --
    # it's clamped to MAX_NEIGHBOR_DEPTH before the call.
    assert captured_depth["depth"] == MAX_NEIGHBOR_DEPTH


def test_get_trace_summary_is_an_honest_stub():
    graph = build_reference_topology()
    tools = AgentTools(graph=graph, change_repo=FakeChangeRepo(), incident_repo=FakeIncidentRepo())
    result = tools.get_trace_summary("ranking-api", datetime(2026, 1, 1), datetime(2026, 1, 1))
    assert result["available"] is False


def test_get_logs_is_an_honest_stub():
    graph = build_reference_topology()
    tools = AgentTools(graph=graph, change_repo=FakeChangeRepo(), incident_repo=FakeIncidentRepo())
    result = tools.get_logs("ranking-api", "error", datetime(2026, 1, 1), datetime(2026, 1, 1))
    assert result["available"] is False
    assert result["lines"] == []


def test_get_incident_history_caps_k():
    graph = build_reference_topology()
    incident_repo = FakeIncidentRepo()
    tools = AgentTools(graph=graph, change_repo=FakeChangeRepo(), incident_repo=incident_repo)
    tools.get_incident_history("latency", k=9999)
    assert incident_repo.last_k <= 20


def test_request_intervention_test_without_injected_fn_reports_unavailable():
    graph = build_reference_topology()
    tools = AgentTools(graph=graph, change_repo=FakeChangeRepo(), incident_repo=FakeIncidentRepo())
    result = tools.request_intervention_test("feature-worker")
    assert result["available"] is False


def test_request_intervention_test_uses_injected_fn_when_present():
    graph = build_reference_topology()
    tools = AgentTools(
        graph=graph,
        change_repo=FakeChangeRepo(),
        incident_repo=FakeIncidentRepo(),
        intervention_test_fn=lambda candidate_id: {"candidate_id": candidate_id, "score": 0.9},
    )
    result = tools.request_intervention_test("feature-worker")
    assert result == {"candidate_id": "feature-worker", "score": 0.9}
