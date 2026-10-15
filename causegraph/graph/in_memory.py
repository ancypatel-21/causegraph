from __future__ import annotations

from collections import deque

from causegraph.graph.repository import (
    Direction,
    GraphRepository,
    downstream_neighbor_of,
    upstream_neighbor_of,
)
from causegraph.schemas import Edge, Node


class InMemoryGraphRepository(GraphRepository):
    """Plain adjacency-list graph. See docs/adr/0003-graph-repository-interface.md."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges_touching: dict[str, list[Edge]] = {}
        self._all_edges: list[Edge] = []

    def add_node(self, node: Node) -> None:
        self._nodes[node.id] = node
        self._edges_touching.setdefault(node.id, [])

    def add_edge(self, edge: Edge) -> None:
        if edge.source not in self._nodes or edge.target not in self._nodes:
            raise ValueError(
                f"edge {edge.source} -{edge.type}-> {edge.target} references unknown node(s)"
            )
        self._all_edges.append(edge)
        self._edges_touching[edge.source].append(edge)
        if edge.target != edge.source:
            self._edges_touching[edge.target].append(edge)

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def all_edges(self) -> list[Edge]:
        return list(self._all_edges)

    def neighbors(
        self,
        node_id: str,
        direction: Direction = Direction.UPSTREAM,
        depth: int = 3,
    ) -> list[tuple[Node, int, list[str]]]:
        if node_id not in self._nodes:
            return []

        results: list[tuple[Node, int, list[str]]] = []
        visited = {node_id}
        queue: deque[tuple[str, int, list[str]]] = deque([(node_id, 0, [node_id])])

        while queue:
            current, dist, path = queue.popleft()
            if dist >= depth:
                continue

            neighbor_ids: set[str] = set()
            for edge in self._edges_touching.get(current, []):
                if direction in (Direction.UPSTREAM, Direction.BOTH):
                    neighbor_id = upstream_neighbor_of(edge, current)
                    if neighbor_id is not None:
                        neighbor_ids.add(neighbor_id)
                if direction in (Direction.DOWNSTREAM, Direction.BOTH):
                    neighbor_id = downstream_neighbor_of(edge, current)
                    if neighbor_id is not None:
                        neighbor_ids.add(neighbor_id)

            for neighbor_id in neighbor_ids:
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                new_path = [*path, neighbor_id]
                node = self._nodes[neighbor_id]
                results.append((node, dist + 1, new_path))
                queue.append((neighbor_id, dist + 1, new_path))

        return results
