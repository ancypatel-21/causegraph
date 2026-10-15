"""Static Sprint-1 reference topology. See docs/adr/0001-service-boundaries.md.

Node ids are stable strings used everywhere: service code, fault injectors,
scenario manifests, and benchmark ground truth all refer to nodes by these
ids, so changing one here is a breaking change to every scenario manifest.
"""

from __future__ import annotations

from causegraph.graph.in_memory import InMemoryGraphRepository
from causegraph.graph.repository import GraphRepository
from causegraph.schemas import Edge, EdgeType, Node, NodeType

EVENT_API = "event-api"
FEATURE_WORKER = "feature-worker"
MODEL_SERVICE = "model-service"
RANKING_API = "ranking-api"
QUALITY_MONITOR = "quality-monitor"
EVENT_STREAM = "event-stream"
FEATURE_STORE = "feature-store"
ENGAGEMENT_FEATURE = "engagement-feature"
RANKING_MODEL = "ranking-model"
RANKING_MODEL_V1 = "ranking-model-v1"


def build_reference_topology() -> GraphRepository:
    repo = InMemoryGraphRepository()

    nodes = [
        Node(id=EVENT_API, type=NodeType.SERVICE, name="event-api"),
        Node(id=FEATURE_WORKER, type=NodeType.SERVICE, name="feature-worker"),
        Node(id=MODEL_SERVICE, type=NodeType.SERVICE, name="model-service"),
        Node(id=RANKING_API, type=NodeType.SERVICE, name="ranking-api"),
        Node(id=QUALITY_MONITOR, type=NodeType.SERVICE, name="quality-monitor"),
        Node(id=EVENT_STREAM, type=NodeType.TOPIC_OR_QUEUE, name="interaction-events"),
        Node(id=FEATURE_STORE, type=NodeType.DATABASE_OR_CACHE, name="feature-store (redis)"),
        Node(id=ENGAGEMENT_FEATURE, type=NodeType.FEATURE, name="engagement-feature"),
        Node(id=RANKING_MODEL, type=NodeType.MODEL, name="ranking-model"),
        Node(id=RANKING_MODEL_V1, type=NodeType.MODEL_VERSION, name="ranking-model-v1"),
    ]
    for node in nodes:
        repo.add_node(node)

    edges = [
        Edge(source=EVENT_API, target=EVENT_STREAM, type=EdgeType.PRODUCES),
        Edge(source=FEATURE_WORKER, target=EVENT_STREAM, type=EdgeType.CONSUMES),
        Edge(source=FEATURE_WORKER, target=ENGAGEMENT_FEATURE, type=EdgeType.GENERATES),
        Edge(source=FEATURE_WORKER, target=FEATURE_STORE, type=EdgeType.WRITES_TO),
        Edge(source=MODEL_SERVICE, target=FEATURE_STORE, type=EdgeType.READS_FROM),
        Edge(source=MODEL_SERVICE, target=ENGAGEMENT_FEATURE, type=EdgeType.USES_FEATURE),
        Edge(source=MODEL_SERVICE, target=RANKING_MODEL_V1, type=EdgeType.SERVES_MODEL),
        Edge(source=RANKING_MODEL_V1, target=RANKING_MODEL, type=EdgeType.DEPENDS_ON),
        Edge(source=RANKING_API, target=MODEL_SERVICE, type=EdgeType.CALLS),
        Edge(source=QUALITY_MONITOR, target=RANKING_API, type=EdgeType.CALLS),
    ]
    for edge in edges:
        repo.add_edge(edge)

    return repo
