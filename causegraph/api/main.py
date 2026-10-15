"""Central causegraph-api service. Implements the "Suggested Internal APIs"
from spec section 10 that Sprint 1 needs: incidents, hypotheses, evidence,
graph neighbors, change events, and benchmark runs. The LLM agent and
remediation endpoints are deliberately not implemented yet (spec section 14,
steps 22-23).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from causegraph.api.deps import (
    get_benchmark_run_repo,
    get_change_repo,
    get_evidence_repo,
    get_graph,
    get_hypothesis_repo,
    get_incident_repo,
    get_rca_baseline,
)
from causegraph.db import init_db
from causegraph.graph.repository import Direction
from causegraph.schemas import BenchmarkRun, ChangeEvent, Evidence, Hypothesis, Incident
from causegraph.telemetry import get_logger, instrument_app
from causegraph.telemetry.metrics import ServiceMetrics, mount_metrics

SERVICE_NAME = "causegraph-api"
logger = get_logger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("causegraph-api started")
    yield


app = FastAPI(title="CauseGraph API", version="0.1.0", lifespan=lifespan)
metrics = ServiceMetrics(SERVICE_NAME)
instrument_app(app, SERVICE_NAME)
mount_metrics(app, metrics)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ---- Incidents -----------------------------------------------------------


class CreateIncidentRequest(BaseModel):
    started_at: datetime
    symptom_nodes: list[str]
    trigger_signal: str
    workload_id: str | None = None
    scenario_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.post("/incidents", response_model=Incident)
def create_incident(payload: CreateIncidentRequest) -> Incident:
    incident = Incident(
        started_at=payload.started_at,
        symptom_nodes=payload.symptom_nodes,
        trigger_signal=payload.trigger_signal,
        workload_id=payload.workload_id,
        scenario_id=payload.scenario_id,
        metadata=payload.metadata,
    )
    return get_incident_repo().create(incident)


@app.get("/incidents/{incident_id}", response_model=Incident)
def get_incident(incident_id: str) -> Incident:
    incident = get_incident_repo().get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


class InvestigateResponse(BaseModel):
    hypotheses: list[Hypothesis]
    evidence: list[Evidence]


@app.post("/incidents/{incident_id}/investigate", response_model=InvestigateResponse)
def investigate_incident(incident_id: str) -> InvestigateResponse:
    incident = get_incident_repo().get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")

    hypotheses, evidence = get_rca_baseline().investigate(incident)

    get_evidence_repo().save_many(evidence)
    get_hypothesis_repo().save_many(hypotheses)
    get_incident_repo().update_status(incident_id, "diagnosed")

    return InvestigateResponse(hypotheses=hypotheses, evidence=evidence)


@app.get("/incidents/{incident_id}/hypotheses", response_model=list[Hypothesis])
def get_hypotheses(incident_id: str) -> list[Hypothesis]:
    return get_hypothesis_repo().for_incident(incident_id)


@app.get("/incidents/{incident_id}/evidence", response_model=list[Evidence])
def get_evidence(incident_id: str) -> list[Evidence]:
    return get_evidence_repo().for_incident(incident_id)


# ---- Graph -----------------------------------------------------------------


class NeighborResult(BaseModel):
    node_id: str
    name: str
    type: str
    distance: int
    path: list[str]


@app.get("/graph/nodes/{node_id}/neighbors", response_model=list[NeighborResult])
def get_neighbors(
    node_id: str, direction: Direction = Direction.UPSTREAM, depth: int = 3
) -> list[NeighborResult]:
    graph = get_graph()
    if graph.get_node(node_id) is None:
        raise HTTPException(status_code=404, detail="node not found")

    results = graph.neighbors(node_id, direction, depth)
    return [
        NeighborResult(node_id=node.id, name=node.name, type=node.type.value, distance=d, path=p)
        for node, d, p in results
    ]


# ---- Change events ----------------------------------------------------------


@app.post("/changes", response_model=ChangeEvent)
def record_change(event: ChangeEvent) -> ChangeEvent:
    return get_change_repo().record(event)


# ---- Benchmark ---------------------------------------------------------------


@app.post("/benchmark/scenarios/{scenario_id}/run", response_model=BenchmarkRun)
def run_benchmark_scenario(scenario_id: str) -> BenchmarkRun:
    from benchmark.evaluator.evaluator import run_scenario

    try:
        return run_scenario(scenario_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/benchmark/runs/{run_id}", response_model=BenchmarkRun)
def get_benchmark_run(run_id: str) -> BenchmarkRun:
    run = get_benchmark_run_repo().get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run
