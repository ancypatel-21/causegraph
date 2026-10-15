from causegraph.graph import Direction, build_reference_topology
from causegraph.graph.topology import (
    EVENT_STREAM,
    FEATURE_WORKER,
    MODEL_SERVICE,
    QUALITY_MONITOR,
    RANKING_API,
)


def test_topology_has_expected_nodes_and_edges():
    graph = build_reference_topology()
    node_ids = {n.id for n in graph.all_nodes()}
    assert {FEATURE_WORKER, MODEL_SERVICE, RANKING_API, QUALITY_MONITOR, EVENT_STREAM} <= node_ids
    assert len(graph.all_edges()) == 10


def test_upstream_traversal_from_quality_monitor_reaches_feature_worker():
    graph = build_reference_topology()
    results = graph.neighbors(QUALITY_MONITOR, Direction.UPSTREAM, depth=6)
    reachable = {node.id: distance for node, distance, _path in results}

    assert RANKING_API in reachable
    assert MODEL_SERVICE in reachable
    assert FEATURE_WORKER in reachable
    assert reachable[RANKING_API] < reachable[MODEL_SERVICE] < reachable[FEATURE_WORKER]


def test_traversal_depth_is_bounded():
    graph = build_reference_topology()
    results = graph.neighbors(QUALITY_MONITOR, Direction.UPSTREAM, depth=1)
    reachable = {node.id for node, _distance, _path in results}
    assert reachable == {RANKING_API}


def test_neighbors_of_unknown_node_is_empty():
    graph = build_reference_topology()
    assert graph.neighbors("does-not-exist") == []
