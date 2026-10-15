"""Shared candidate-collection helper used by every RCA method that starts
from an incident's symptom node(s) and needs the set of plausible upstream
causes (graph-only baseline, B4, and the full CauseGraph scoring in
causegraph/rca/causegraph_method.py)."""

from __future__ import annotations

from causegraph.graph.repository import Direction, GraphRepository


def collect_upstream_candidates(
    graph: GraphRepository, symptom_nodes: list[str], depth: int
) -> dict[str, tuple[int, list[str]]]:
    """Union of upstream nodes (including the symptom nodes themselves at
    distance 0) across all symptom nodes, keeping the shortest path to each
    candidate. Returns {node_id: (distance, path_from_symptom_to_candidate)}."""
    candidates: dict[str, tuple[int, list[str]]] = {}
    for symptom in symptom_nodes:
        candidates[symptom] = (0, [symptom])
        for node, distance, path in graph.neighbors(symptom, Direction.UPSTREAM, depth):
            existing = candidates.get(node.id)
            if existing is None or distance < existing[0]:
                candidates[node.id] = (distance, path)
    return candidates
