"""Incident / Hypothesis / Evidence / BenchmarkRun persistence.

Thin repositories over causegraph.db, converting to/from the Pydantic
schemas in causegraph.schemas so callers (API, benchmark evaluator) never
touch SQLAlchemy rows directly.
"""

from __future__ import annotations

from causegraph.db import BenchmarkRunRow, EvidenceRow, HypothesisRow, IncidentRow, session_scope
from causegraph.schemas import BenchmarkRun, Evidence, Hypothesis, Incident


class IncidentRepository:
    def create(self, incident: Incident) -> Incident:
        with session_scope() as session:
            session.add(
                IncidentRow(
                    id=incident.id,
                    started_at=incident.started_at,
                    detected_at=incident.detected_at,
                    symptom_nodes=incident.symptom_nodes,
                    trigger_signal=incident.trigger_signal,
                    status=incident.status.value,
                    workload_id=incident.workload_id,
                    scenario_id=incident.scenario_id,
                    metadata_json=incident.metadata,
                )
            )
        return incident

    def get(self, incident_id: str) -> Incident | None:
        with session_scope() as session:
            row = session.get(IncidentRow, incident_id)
            if row is None:
                return None
            return Incident(
                id=row.id,
                started_at=row.started_at,
                detected_at=row.detected_at,
                symptom_nodes=row.symptom_nodes or [],
                trigger_signal=row.trigger_signal,
                status=row.status,
                workload_id=row.workload_id,
                scenario_id=row.scenario_id,
                metadata=row.metadata_json or {},
            )

    def recent_by_trigger_signal(self, signature: str, k: int = 5) -> list[Incident]:
        """Backs the agent's get_incident_history(signature, k) tool (spec
        section 6.1). Capped at k<=50 regardless of what's requested."""
        k = min(k, 50)
        with session_scope() as session:
            rows = (
                session.query(IncidentRow)
                .filter(IncidentRow.trigger_signal == signature)
                .order_by(IncidentRow.started_at.desc())
                .limit(k)
                .all()
            )
            return [
                Incident(
                    id=row.id,
                    started_at=row.started_at,
                    detected_at=row.detected_at,
                    symptom_nodes=row.symptom_nodes or [],
                    trigger_signal=row.trigger_signal,
                    status=row.status,
                    workload_id=row.workload_id,
                    scenario_id=row.scenario_id,
                    metadata=row.metadata_json or {},
                )
                for row in rows
            ]

    def update_status(self, incident_id: str, status: str) -> None:
        with session_scope() as session:
            row = session.get(IncidentRow, incident_id)
            if row is not None:
                row.status = status


class EvidenceRepository:
    def save_many(self, items: list[Evidence]) -> None:
        with session_scope() as session:
            for item in items:
                session.add(
                    EvidenceRow(
                        id=item.id,
                        incident_id=item.incident_id,
                        candidate_node=item.candidate_node,
                        evidence_type=item.evidence_type,
                        source=item.source,
                        observed_at=item.observed_at,
                        value=item.value,
                        reliability=item.reliability,
                        supports=item.supports,
                    )
                )

    def for_incident(self, incident_id: str) -> list[Evidence]:
        with session_scope() as session:
            rows = (
                session.query(EvidenceRow)
                .filter(EvidenceRow.incident_id == incident_id)
                .all()
            )
            return [
                Evidence(
                    id=r.id,
                    incident_id=r.incident_id,
                    candidate_node=r.candidate_node,
                    evidence_type=r.evidence_type,
                    source=r.source,
                    observed_at=r.observed_at,
                    value=r.value or {},
                    reliability=r.reliability,
                    supports=r.supports,
                )
                for r in rows
            ]


class HypothesisRepository:
    def save_many(self, items: list[Hypothesis]) -> None:
        with session_scope() as session:
            for item in items:
                session.add(
                    HypothesisRow(
                        incident_id=item.incident_id,
                        candidate_node=item.candidate_node,
                        rank=item.rank,
                        score=item.score,
                        score_components=item.score_components,
                        causal_path=item.causal_path,
                        evidence_ids=item.evidence_ids,
                        contradicting_evidence_ids=item.contradicting_evidence_ids,
                    )
                )

    def for_incident(self, incident_id: str) -> list[Hypothesis]:
        with session_scope() as session:
            rows = (
                session.query(HypothesisRow)
                .filter(HypothesisRow.incident_id == incident_id)
                .order_by(HypothesisRow.rank.asc())
                .all()
            )
            return [
                Hypothesis(
                    incident_id=r.incident_id,
                    candidate_node=r.candidate_node,
                    rank=r.rank,
                    score=r.score,
                    score_components=r.score_components or {},
                    causal_path=r.causal_path or [],
                    evidence_ids=r.evidence_ids or [],
                    contradicting_evidence_ids=r.contradicting_evidence_ids or [],
                )
                for r in rows
            ]


class BenchmarkRunRepository:
    def save(self, run: BenchmarkRun) -> BenchmarkRun:
        with session_scope() as session:
            session.add(
                BenchmarkRunRow(
                    id=run.id,
                    git_sha=run.git_sha,
                    scenario_id=run.scenario_id,
                    scenario_version=run.scenario_version,
                    seed=run.seed,
                    workload_config=run.workload_config,
                    method=run.method,
                    method_config=run.method_config,
                    llm_config=run.llm_config,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    metrics=run.metrics,
                )
            )
        return run

    def get(self, run_id: str) -> BenchmarkRun | None:
        with session_scope() as session:
            row = session.get(BenchmarkRunRow, run_id)
            if row is None:
                return None
            return BenchmarkRun(
                id=row.id,
                git_sha=row.git_sha,
                scenario_id=row.scenario_id,
                scenario_version=row.scenario_version,
                seed=row.seed,
                workload_config=row.workload_config or {},
                method=row.method,
                method_config=row.method_config or {},
                llm_config=row.llm_config,
                started_at=row.started_at,
                finished_at=row.finished_at,
                metrics=row.metrics or {},
            )
