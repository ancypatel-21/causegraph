from datetime import datetime

from causegraph.agent import AgentTools, InvestigatorAgent
from causegraph.graph import build_reference_topology
from causegraph.graph.topology import FEATURE_WORKER, MODEL_SERVICE, RANKING_API
from causegraph.schemas import Evidence, Hypothesis, Incident


class FakeChangeRepo:
    def recent_for_node(self, node_id, start, end):
        return []


class FakeIncidentRepo:
    def recent_by_trigger_signal(self, signature, k):
        return []


def _hypothesis(node_id: str, rank: int, score: float, evidence_ids=None) -> Hypothesis:
    return Hypothesis(
        incident_id="inc-1",
        candidate_node=node_id,
        rank=rank,
        score=score,
        score_components={"A": score},
        causal_path=[node_id, RANKING_API],
        evidence_ids=evidence_ids or [],
        contradicting_evidence_ids=[],
    )


def _agent() -> InvestigatorAgent:
    graph = build_reference_topology()
    tools = AgentTools(graph=graph, change_repo=FakeChangeRepo(), incident_repo=FakeIncidentRepo())
    return InvestigatorAgent(tools)  # default provider: deterministic mock, no network


def test_agent_picks_a_candidate_from_the_rca_engines_own_hypothesis_set():
    agent = _agent()
    incident = Incident(
        started_at=datetime(2026, 1, 1),
        symptom_nodes=[RANKING_API],
        trigger_signal="incompatible_schema",
    )
    ev = Evidence(
        incident_id=incident.id,
        candidate_node=FEATURE_WORKER,
        evidence_type="feature_null_rate",
        source="prometheus",
        observed_at=datetime(2026, 1, 1),
        value={},
        reliability=0.7,
        supports=True,
    )
    hypotheses = [
        _hypothesis(FEATURE_WORKER, rank=1, score=8.0, evidence_ids=[ev.id]),
        _hypothesis(MODEL_SERVICE, rank=2, score=1.0),
    ]

    report = agent.investigate(incident, hypotheses, [ev])

    # The agent must never invent a candidate the RCA engine didn't surface.
    assert report.root_cause.node_id in {FEATURE_WORKER, MODEL_SERVICE}
    assert 0.0 <= report.confidence <= 1.0
    assert report.needs_human_approval is True
    assert report.incident_id == incident.id


def test_agent_never_proposes_autonomous_approval():
    agent = _agent()
    incident = Incident(
        started_at=datetime(2026, 1, 1), symptom_nodes=[RANKING_API], trigger_signal="latency"
    )
    hypotheses = [_hypothesis(MODEL_SERVICE, rank=1, score=5.0)]

    report = agent.investigate(incident, hypotheses, [])

    # Phase 10 (remediation policy engine) does not exist yet -- the agent
    # must never claim a diagnosis can be auto-approved.
    assert report.needs_human_approval is True


def test_agent_evidence_ids_trace_back_to_the_chosen_hypothesis():
    agent = _agent()
    incident = Incident(
        started_at=datetime(2026, 1, 1), symptom_nodes=[RANKING_API], trigger_signal="latency"
    )
    hypotheses = [_hypothesis(MODEL_SERVICE, rank=1, score=5.0, evidence_ids=["ev-abc"])]

    report = agent.investigate(incident, hypotheses, [])

    chosen = next(h for h in hypotheses if h.candidate_node == report.root_cause.node_id)
    assert report.supporting_evidence_ids == chosen.evidence_ids


def test_agent_alternative_hypotheses_exclude_the_chosen_root_cause():
    agent = _agent()
    incident = Incident(
        started_at=datetime(2026, 1, 1), symptom_nodes=[RANKING_API], trigger_signal="latency"
    )
    hypotheses = [
        _hypothesis(FEATURE_WORKER, rank=1, score=9.0),
        _hypothesis(MODEL_SERVICE, rank=2, score=2.0),
    ]

    report = agent.investigate(incident, hypotheses, [])

    assert report.root_cause.node_id not in {a.node_id for a in report.alternative_hypotheses}


def test_agent_supporting_and_contradicting_evidence_ids_never_overlap():
    agent = _agent()
    incident = Incident(
        started_at=datetime(2026, 1, 1),
        symptom_nodes=[RANKING_API],
        trigger_signal="incompatible_schema",
    )
    supporting_ev = Evidence(
        incident_id=incident.id,
        candidate_node=FEATURE_WORKER,
        evidence_type="feature_null_rate",
        source="prometheus",
        observed_at=datetime(2026, 1, 1),
        value={},
        reliability=0.7,
        supports=True,
    )
    contradicting_ev = Evidence(
        incident_id=incident.id,
        candidate_node=FEATURE_WORKER,
        evidence_type="feature_null_rate",
        source="prometheus",
        observed_at=datetime(2026, 1, 1),
        value={},
        reliability=0.7,
        supports=False,
    )
    # A Hypothesis's evidence_ids can legitimately include both (it means
    # "all evidence for this candidate"), but the agent's report fields
    # promise disjoint sets by name.
    hypotheses = [
        _hypothesis(
            FEATURE_WORKER, rank=1, score=8.0, evidence_ids=[supporting_ev.id, contradicting_ev.id]
        )
    ]

    report = agent.investigate(incident, hypotheses, [supporting_ev, contradicting_ev])

    assert contradicting_ev.id in report.contradicting_evidence_ids
    assert contradicting_ev.id not in report.supporting_evidence_ids
    assert supporting_ev.id in report.supporting_evidence_ids


def test_agent_requires_at_least_one_hypothesis():
    import pytest

    agent = _agent()
    incident = Incident(
        started_at=datetime(2026, 1, 1), symptom_nodes=[RANKING_API], trigger_signal="latency"
    )
    with pytest.raises(ValueError):
        agent.investigate(incident, [], [])
