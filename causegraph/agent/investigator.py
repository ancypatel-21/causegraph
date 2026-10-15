"""Investigator agent (spec section 6): "an evidence orchestrator, not an
omnipotent operator." It never re-ranks from scratch -- it takes the RCA
engine's already-ranked Hypothesis/Evidence list (the source of truth,
spec section 4.3), may call a couple of bounded tools to fill gaps, and
writes the required structured conclusion (spec section 6.2). It
recommends an action type, but recommending is all it does: executing it
still goes through the policy engine and (for anything above low-risk) a
human approval, per causegraph/remediation/.
"""

from __future__ import annotations

from datetime import timedelta

from causegraph.agent.tools import AgentTools
from causegraph.llm import CandidateContext, LLMProvider, get_default_provider
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.remediation import FAULT_TO_ACTION_TYPE
from causegraph.schemas import (
    AgentReport,
    AlternativeHypothesis,
    Evidence,
    Hypothesis,
    Incident,
    RecommendedAction,
    RootCause,
)

CHANGE_LOOKBACK = timedelta(minutes=5)
TOP_N_FOR_SYNTHESIS = 5


def _cause_type(node_id: str) -> str:
    signal = NODE_SIGNALS.get(node_id)
    return signal.evidence_type if signal is not None else "unknown"


def _recommend_action(node_id: str, incident: Incident) -> RecommendedAction:
    # Uses the same trigger_signal the benchmark harness already relies
    # on to pick a fault injector -- here it picks a real, allow-listed
    # action_type instead (causegraph/remediation/policy.py). Recommending
    # it is all this does; whether it's actually allowed and whether it
    # needs approval is decided by PolicyEngine.evaluate at execution
    # time, not by the agent.
    action_type = FAULT_TO_ACTION_TYPE.get(incident.trigger_signal, "manual_review")
    return RecommendedAction(action_type=action_type, target=node_id)


class InvestigatorAgent:
    def __init__(self, tools: AgentTools, provider: LLMProvider | None = None) -> None:
        self.tools = tools
        self.provider = provider or get_default_provider()

    def investigate(
        self, incident: Incident, hypotheses: list[Hypothesis], evidence: list[Evidence]
    ) -> AgentReport:
        if not hypotheses:
            raise ValueError("agent requires at least one ranked hypothesis from the RCA engine")

        top_hypotheses = hypotheses[:TOP_N_FOR_SYNTHESIS]
        evidence_by_node: dict[str, list[Evidence]] = {}
        for ev in evidence:
            evidence_by_node.setdefault(ev.candidate_node, []).append(ev)

        # Bounded tool use: fill in anything the RCA engine's evidence
        # didn't already carry for the leading candidate, instead of
        # dumping the whole telemetry lake into the prompt.
        leading_node = top_hypotheses[0].candidate_node
        changes = self.tools.get_recent_changes(
            leading_node, incident.started_at - CHANGE_LOOKBACK, incident.started_at
        )
        history = self.tools.get_incident_history(incident.trigger_signal, k=5)

        contexts = [
            CandidateContext(
                node_id=h.candidate_node,
                node_type=_cause_type(h.candidate_node),
                raw_signals=h.score_components,
                # causal_path is always [candidate, ..., symptom] regardless
                # of which RCA method produced it, unlike score_components'
                # keys, which differ per method -- this is the one distance
                # signal every method's Hypothesis carries consistently.
                graph_distance=max(0, len(h.causal_path) - 1),
                recent_changes=[f"{c['type']} at {c['timestamp']}" for c in changes]
                if h.candidate_node == leading_node
                else [],
            )
            for h in top_hypotheses
        ]

        summary = (
            f"incident={incident.id} trigger={incident.trigger_signal} "
            f"symptom_nodes={incident.symptom_nodes}; "
            f"{len(history)} prior incident(s) with this trigger signal"
        )
        result = self.provider.rank_candidates(summary, contexts)

        chosen_node = result.ranked_node_ids[0] if result.ranked_node_ids else leading_node
        chosen = next((h for h in top_hypotheses if h.candidate_node == chosen_node), top_hypotheses[0])

        alternatives = [
            AlternativeHypothesis(
                node_id=h.candidate_node,
                cause_type=_cause_type(h.candidate_node),
                confidence=max(0.0, result.confidence - 0.15 * (i + 1)),
            )
            for i, h in enumerate(top_hypotheses)
            if h.candidate_node != chosen_node
        ][:3]

        contradicting_ids = list(
            dict.fromkeys(
                chosen.contradicting_evidence_ids
                + [
                    ev.id
                    for ev in evidence_by_node.get(chosen.candidate_node, [])
                    if not ev.supports
                ]
            )
        )
        # A Hypothesis's evidence_ids (causegraph/rca) is "all evidence for
        # this candidate," not necessarily disjoint from its
        # contradicting_evidence_ids. The agent's report uses the stricter,
        # genuinely-disjoint meaning its field names promise (spec section
        # 6.2's own example shows non-overlapping lists).
        supporting_ids = [eid for eid in chosen.evidence_ids if eid not in contradicting_ids]

        return AgentReport(
            incident_id=incident.id,
            root_cause=RootCause(node_id=chosen_node, cause_type=_cause_type(chosen_node)),
            confidence=result.confidence,
            causal_path=chosen.causal_path,
            supporting_evidence_ids=supporting_ids,
            contradicting_evidence_ids=contradicting_ids,
            alternative_hypotheses=alternatives,
            recommended_action=_recommend_action(chosen_node, incident),
            needs_human_approval=True,
        )
