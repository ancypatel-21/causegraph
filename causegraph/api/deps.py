"""Process-wide singletons for the causegraph-api service."""

from __future__ import annotations

from functools import lru_cache

from causegraph.changes import ChangeEventRepository
from causegraph.graph import GraphRepository, build_reference_topology
from causegraph.persistence import (
    BenchmarkRunRepository,
    EvidenceRepository,
    HypothesisRepository,
    IncidentRepository,
    RemediationProposalRepository,
)
from causegraph.rca import GraphOnlyBaseline
from causegraph.remediation import RemediationExecutor


@lru_cache
def get_graph() -> GraphRepository:
    return build_reference_topology()


@lru_cache
def get_rca_baseline() -> GraphOnlyBaseline:
    return GraphOnlyBaseline(get_graph())


@lru_cache
def get_incident_repo() -> IncidentRepository:
    return IncidentRepository()


@lru_cache
def get_evidence_repo() -> EvidenceRepository:
    return EvidenceRepository()


@lru_cache
def get_hypothesis_repo() -> HypothesisRepository:
    return HypothesisRepository()


@lru_cache
def get_change_repo() -> ChangeEventRepository:
    return ChangeEventRepository()


@lru_cache
def get_benchmark_run_repo() -> BenchmarkRunRepository:
    return BenchmarkRunRepository()


@lru_cache
def get_remediation_proposal_repo() -> RemediationProposalRepository:
    return RemediationProposalRepository()


@lru_cache
def get_remediation_executor() -> RemediationExecutor:
    return RemediationExecutor(repo=get_remediation_proposal_repo())
