"""CauseGraph (CG): "Graph + anomaly/change/propagation scoring +
causal/intervention evidence + bounded agent synthesis" (spec section 9.1).

This module implements the *scoring* half of CG -- the initial scoring
model from spec section 5.2:

    score(c) = w1*A(c) + w2*D(c,s) + w3*T(c) + w4*C(c) + w5*P(c,s)
               + w6*I(c) - w7*X(c)

The agent-synthesis half (bounded evidence tools, structured report) is a
separate layer added on top in causegraph/agent/ (Phase 8) -- per the
spec's own evidence-model rule, the ranked, numeric score below is the
source of truth; the agent explains it, it does not re-decide it.

Per spec section 5.2 ("Start interpretable. Do not train a complex model
until the benchmark exists... Weights are tuned on a training/development
subset only"), the weights here are fixed, documented defaults, not
tuned -- there are only 3 scenarios in Sprint 1, nowhere near enough for a
dev/held-out split (see docs/research-protocol.md).

Ablations (spec section 9.2) are implemented as the `enabled_terms`
parameter: dropping a letter from the default set reproduces "CauseGraph
without X evidence" exactly, with no separate code path to maintain.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from causegraph.anomalies import RobustZScoreDetector
from causegraph.changes import ChangeEventRepository
from causegraph.graph.repository import GraphRepository
from causegraph.graph.traversal import collect_upstream_candidates
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.schemas import Evidence, Hypothesis, Incident

DEFAULT_TRAVERSAL_DEPTH = 6
DEFAULT_INCIDENT_WINDOW = timedelta(seconds=15)
CHANGE_LOOKBACK = timedelta(minutes=5)
ANOMALY_SUPPORT_THRESHOLD = 1.5
QUIET_THRESHOLD = 0.5  # below this, a candidate looks healthy (contradicting evidence)
SEVERITY_NORMALIZATION_CAP = 10.0  # caps A(c)/P(c,s) contributions so one huge z-score can't dominate

# Fixed, documented, *untuned* starting weights (spec section 5.2).
DEFAULT_WEIGHTS: dict[str, float] = {
    "A": 1.0,
    "D": 0.5,
    "T": 1.5,
    "C": 2.0,
    "P": 1.5,
    "I": 3.0,
    "X": 1.0,
}

ALL_TERMS = frozenset(DEFAULT_WEIGHTS.keys())

# Type of a pluggable intervention-evidence provider: given a candidate node
# id and the incident, return I(c) in [0, 1]. Phase 7's InterventionTester
# implements this signature; absent it, I(c) is always 0.0 (no evidence,
# never a penalty -- spec section 5.3 treats intervention evidence as
# something you *add* when available, not something whose absence counts
# against a candidate).
InterventionScorer = Callable[[str, Incident], float]


def _no_intervention_evidence(_node_id: str, _incident: Incident) -> float:
    return 0.0


def _normalize_severity(severity: float) -> float:
    return min(severity, SEVERITY_NORMALIZATION_CAP) / SEVERITY_NORMALIZATION_CAP


class CauseGraphMethod:
    method_name = "causegraph"

    def __init__(
        self,
        graph: GraphRepository,
        detector: RobustZScoreDetector | None = None,
        change_repo: ChangeEventRepository | None = None,
        intervention_scorer: InterventionScorer | None = None,
        weights: dict[str, float] | None = None,
        enabled_terms: frozenset[str] | None = None,
    ) -> None:
        self.graph = graph
        self.detector = detector or RobustZScoreDetector()
        self.change_repo = change_repo or ChangeEventRepository()
        self.intervention_scorer = intervention_scorer or _no_intervention_evidence
        self.weights = weights or DEFAULT_WEIGHTS
        self.enabled_terms = enabled_terms if enabled_terms is not None else ALL_TERMS

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
        early_end = incident_start + (incident_window / 2)

        # A(c): full-window anomaly severity per candidate, reused for P(c,s) too.
        severities: dict[str, float] = {}
        has_data: dict[str, bool] = {}
        for node_id in candidate_paths:
            signal = NODE_SIGNALS.get(node_id)
            if signal is None:
                severities[node_id] = 0.0
                has_data[node_id] = False
                continue
            anomaly = self.detector.score(
                node_id, signal.query, incident_start, incident_end, direction=signal.direction
            )
            severities[node_id] = anomaly.severity
            has_data[node_id] = anomaly.has_data

        # T(c): early-window severity, to detect "this candidate was already
        # anomalous before the symptom nodes themselves were."
        symptom_early_severity = 0.0
        for symptom_node in incident.symptom_nodes:
            signal = NODE_SIGNALS.get(symptom_node)
            if signal is None:
                continue
            early = self.detector.score(
                symptom_node, signal.query, incident_start, early_end, direction=signal.direction
            )
            symptom_early_severity = max(symptom_early_severity, early.severity)

        evidence: list[Evidence] = []
        scored: list[tuple[str, float, dict[str, float]]] = []

        for node_id, (distance, path) in candidate_paths.items():
            components = self._score_candidate(
                node_id=node_id,
                distance=distance,
                path=path,
                incident=incident,
                incident_start=incident_start,
                early_end=early_end,
                incident_end=incident_end,
                severities=severities,
                has_data=has_data,
                symptom_early_severity=symptom_early_severity,
            )
            total = sum(
                self.weights[term] * value * (1 if term != "X" else -1)
                for term, value in components.items()
            )
            scored.append((node_id, total, components))

            if has_data.get(node_id):
                signal = NODE_SIGNALS[node_id]
                evidence.append(
                    Evidence(
                        incident_id=incident.id,
                        candidate_node=node_id,
                        evidence_type=signal.evidence_type,
                        source="causegraph",
                        observed_at=incident_end,
                        value={"severity": severities[node_id], **components},
                        reliability=0.85,
                        supports=severities[node_id] >= ANOMALY_SUPPORT_THRESHOLD,
                    )
                )

        scored.sort(key=lambda row: row[1], reverse=True)

        evidence_by_node: dict[str, list[str]] = {}
        for ev in evidence:
            evidence_by_node.setdefault(ev.candidate_node, []).append(ev.id)

        hypotheses = [
            Hypothesis(
                incident_id=incident.id,
                candidate_node=node_id,
                rank=rank,
                score=score,
                score_components=components,
                causal_path=list(reversed(candidate_paths[node_id][1])),
                evidence_ids=evidence_by_node.get(node_id, []),
                contradicting_evidence_ids=[
                    e.id for e in evidence if e.candidate_node == node_id and not e.supports
                ],
            )
            for rank, (node_id, score, components) in enumerate(scored[:top_k], start=1)
        ]
        return hypotheses, evidence

    def _score_candidate(
        self,
        node_id: str,
        distance: int,
        path: list[str],
        incident: Incident,
        incident_start: datetime,
        early_end: datetime,
        incident_end: datetime,
        severities: dict[str, float],
        has_data: dict[str, bool],
        symptom_early_severity: float,
    ) -> dict[str, float]:
        components: dict[str, float] = {}

        if "A" in self.enabled_terms:
            components["A"] = _normalize_severity(severities.get(node_id, 0.0))

        if "D" in self.enabled_terms:
            components["D"] = 1.0 / (1 + distance)

        if "T" in self.enabled_terms:
            signal = NODE_SIGNALS.get(node_id)
            if signal is not None and node_id not in incident.symptom_nodes:
                early = self.detector.score(
                    node_id, signal.query, incident_start, early_end, direction=signal.direction
                )
                lead = early.severity - symptom_early_severity
                components["T"] = max(0.0, min(1.0, lead / SEVERITY_NORMALIZATION_CAP))
            else:
                components["T"] = 0.0

        if "C" in self.enabled_terms:
            changes = self.change_repo.recent_for_node(
                node_id, incident_start - CHANGE_LOOKBACK, incident_end
            )
            components["C"] = 1.0 if changes else 0.0

        if "P" in self.enabled_terms:
            path_severities = [severities.get(n, 0.0) for n in path if n in severities]
            normalized = [_normalize_severity(s) for s in path_severities]
            components["P"] = sum(normalized) / len(normalized) if normalized else 0.0

        if "I" in self.enabled_terms:
            components["I"] = max(0.0, min(1.0, self.intervention_scorer(node_id, incident)))

        if "X" in self.enabled_terms:
            # A healthy control requires an actual observation, not merely
            # the absence of one -- a node we have no telemetry for is
            # "unknown," not "proven quiet," and must not be penalized.
            severity = severities.get(node_id, 0.0)
            components["X"] = 1.0 if has_data.get(node_id) and severity < QUIET_THRESHOLD else 0.0

        return components
