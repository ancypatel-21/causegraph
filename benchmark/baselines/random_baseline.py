"""B0: random / topology-naive baseline (spec section 9.1): "Sanity floor;
select among eligible components without telemetry reasoning." Any RCA
method that cannot clearly beat this on held-out scenarios is not adding
value.
"""

from __future__ import annotations

import random
from datetime import timedelta

from causegraph.graph.repository import GraphRepository
from causegraph.schemas import Hypothesis, Incident


class RandomBaseline:
    method_name = "random"

    def __init__(self, graph: GraphRepository) -> None:
        self.graph = graph

    def investigate(
        self,
        incident: Incident,
        incident_window: timedelta | None = None,  # unused: this baseline ignores telemetry entirely
        top_k: int = 5,
    ) -> tuple[list[Hypothesis], list]:
        # Deterministic given the incident id, so a result is reproducible
        # without implying the ranking itself is meaningful.
        rng = random.Random(incident.id)
        eligible = [n.id for n in self.graph.all_nodes()]
        rng.shuffle(eligible)

        hypotheses = [
            Hypothesis(
                incident_id=incident.id,
                candidate_node=node_id,
                rank=rank,
                score=1.0 / rank,  # arbitrary monotonic placeholder, not a real signal
                score_components={},
                causal_path=[node_id],
                evidence_ids=[],
                contradicting_evidence_ids=[],
            )
            for rank, node_id in enumerate(eligible[:top_k], start=1)
        ]
        return hypotheses, []
