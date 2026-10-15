"""Graph repository interface. See docs/adr/0003-graph-repository-interface.md."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from causegraph.schemas import Edge, EdgeType, Node


class Direction(StrEnum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    BOTH = "both"


# Most edge types describe "source depends on target" (a caller, reader, or
# consumer naming what it relies on), so target is upstream of source --
# e.g. CALLS: ranking-api -> model-service means model-service is upstream
# of ranking-api. A few edge types describe the opposite: a creator naming
# what it creates (PRODUCES/WRITES_TO/GENERATES), so source is upstream of
# target -- e.g. GENERATES: feature-worker -> engagement-feature means
# feature-worker is upstream of the feature it generates. This set lists
# the "creator -> created" exceptions; everything else is "dependent ->
# dependency".
CREATOR_EDGE_TYPES = {EdgeType.PRODUCES, EdgeType.WRITES_TO, EdgeType.GENERATES}


def upstream_neighbor_of(edge: Edge, current_node_id: str) -> str | None:
    """Given an edge touching current_node_id, return the node that is
    upstream of current_node_id along this edge, or None if this edge does
    not place current_node_id on the downstream side."""
    is_creator_edge = edge.type in CREATOR_EDGE_TYPES
    if is_creator_edge:
        # source is upstream of target
        return edge.source if edge.target == current_node_id else None
    # target is upstream of source
    return edge.target if edge.source == current_node_id else None


def downstream_neighbor_of(edge: Edge, current_node_id: str) -> str | None:
    """The inverse of upstream_neighbor_of: the node downstream of
    current_node_id along this edge, or None if not applicable."""
    is_creator_edge = edge.type in CREATOR_EDGE_TYPES
    if is_creator_edge:
        return edge.target if edge.source == current_node_id else None
    return edge.source if edge.target == current_node_id else None


class GraphRepository(ABC):
    """Storage-agnostic interface for the dependency graph.

    "Upstream" follows edges backwards (target -> source): if A CALLS B, then
    B is upstream of A, matching the RCA engine's need to walk from a symptom
    toward its possible causes.
    """

    @abstractmethod
    def add_node(self, node: Node) -> None: ...

    @abstractmethod
    def add_edge(self, edge: Edge) -> None: ...

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None: ...

    @abstractmethod
    def all_nodes(self) -> list[Node]: ...

    @abstractmethod
    def all_edges(self) -> list[Edge]: ...

    @abstractmethod
    def neighbors(
        self,
        node_id: str,
        direction: Direction = Direction.UPSTREAM,
        depth: int = 3,
    ) -> list[tuple[Node, int, list[str]]]:
        """Return (node, distance, path_from_start) for reachable nodes within depth."""
        ...
