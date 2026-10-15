"""Shared data schemas for CauseGraph.

These are the typed contracts every module (graph, telemetry, anomalies, rca,
benchmark, api) exchanges. Per the spec: "All RCA conclusions should be
reconstructable from stored evidence objects. LLM prose is not the source of
truth." These models are that source of truth.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


class NodeType(StrEnum):
    SERVICE = "service"
    DATA_PIPELINE = "data_pipeline"
    TOPIC_OR_QUEUE = "topic_or_queue"
    DATABASE_OR_CACHE = "database_or_cache"
    FEATURE = "feature"
    MODEL = "model"
    MODEL_VERSION = "model_version"
    DEPLOYMENT = "deployment"
    ENDPOINT = "endpoint"
    METRIC_OR_SIGNAL = "metric_or_signal"


class EdgeType(StrEnum):
    CALLS = "CALLS"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    GENERATES = "GENERATES"
    USES_FEATURE = "USES_FEATURE"
    SERVES_MODEL = "SERVES_MODEL"
    DEPENDS_ON = "DEPENDS_ON"
    DEPLOYED_AS = "DEPLOYED_AS"
    CHANGED_BY = "CHANGED_BY"


class Node(BaseModel):
    id: str
    type: NodeType
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    source: str
    target: str
    type: EdgeType
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    DIAGNOSED = "diagnosed"
    CLOSED = "closed"


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("inc"))
    started_at: datetime
    detected_at: datetime | None = None
    symptom_nodes: list[str]
    trigger_signal: str
    status: IncidentStatus = IncidentStatus.OPEN
    workload_id: str | None = None
    scenario_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("ev"))
    incident_id: str
    candidate_node: str
    evidence_type: str
    source: str
    observed_at: datetime
    value: dict[str, Any] = Field(default_factory=dict)
    reliability: float = Field(ge=0.0, le=1.0)
    supports: bool


class Hypothesis(BaseModel):
    incident_id: str
    candidate_node: str
    rank: int
    score: float
    score_components: dict[str, float] = Field(default_factory=dict)
    causal_path: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class ChangeEvent(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("chg"))
    node_id: str
    type: str
    version_before: str | None = None
    version_after: str | None = None
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scenario(BaseModel):
    id: str
    seed: int
    root_cause: str
    fault: str
    inject_at_seconds: int
    symptom_nodes: list[str]
    expected_path: list[str]
    cleanup: str
    severity: str
    labels: list[str] = Field(default_factory=list)


class BenchmarkRun(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("run"))
    git_sha: str
    scenario_id: str
    scenario_version: str
    seed: int
    workload_config: dict[str, Any] = Field(default_factory=dict)
    method: str
    method_config: dict[str, Any] = Field(default_factory=dict)
    llm_config: dict[str, Any] | None = None
    started_at: datetime
    finished_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class RootCause(BaseModel):
    node_id: str
    cause_type: str


class RecommendedAction(BaseModel):
    action_type: str
    target: str


class AlternativeHypothesis(BaseModel):
    node_id: str
    cause_type: str
    confidence: float = Field(ge=0.0, le=1.0)


class AgentReport(BaseModel):
    """The investigator agent's required structured output (spec section
    6.2). This is the agent's write-up of an already-ranked diagnosis, not
    a separate ranking -- the RCA engine's Hypothesis/Evidence objects
    remain the source of truth (spec section 4.3)."""

    incident_id: str
    root_cause: RootCause
    confidence: float = Field(ge=0.0, le=1.0)
    causal_path: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    alternative_hypotheses: list[AlternativeHypothesis] = Field(default_factory=list)
    recommended_action: RecommendedAction
    needs_human_approval: bool = True
