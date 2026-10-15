"""Benchmark evaluator: injects a scenario's fault into the real running
services, diagnoses the resulting incident with an RCA method, scores the
diagnosis against ground truth, and persists a reproducible artifact. See
spec section 9.3 (metrics) and docs/adr/0004-benchmark-artifact-format.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from causegraph.agent import AgentTools, InvestigatorAgent
from causegraph.graph import build_reference_topology
from causegraph.persistence import (
    BenchmarkRunRepository,
    EvidenceRepository,
    HypothesisRepository,
    IncidentRepository,
)
from causegraph.rca import CauseGraphMethod
from causegraph.schemas import BenchmarkRun, Incident, Scenario
from causegraph.telemetry import get_logger

from benchmark.baselines import get_method
from benchmark.evaluator.intervention_runner import run_intervention_test
from benchmark.injectors import get_injector
from benchmark.scenarios import load_scenario, scenario_version
from benchmark.workloads import run_workload

logger = get_logger("benchmark-evaluator")

EVENT_API_URL = os.environ.get("EVENT_API_URL", "http://localhost:8001")
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "experiments" / "results"

# Time for the workload to establish a healthy baseline before the fault is
# injected, and time to let the symptom manifest in metrics before the RCA
# method runs. Tuned to Prometheus's short scrape interval for Sprint 1
# (see infra/observability/prometheus.yml), not to real incident timescales.
POST_INJECT_SETTLE_SECONDS = 15.0

# Intervention testing (spec section 5.3) is benchmark/dev-mode only and
# opt-in: it mutates live fault state mid-run and adds wall-clock time, so
# it must never silently change what a plain `run-scenario` call does.
ALLOW_INTERVENTION_TESTS = os.environ.get("ALLOW_INTERVENTION_TESTS") == "1"
INTERVENTION_RECOVERY_SECONDS = float(os.environ.get("INTERVENTION_RECOVERY_SECONDS", "10.0"))

# Agent synthesis (spec section 6/8) is opt-in and additive: it never
# changes the ranked Hypothesis list or the accuracy metrics, only adds an
# AgentReport write-up on top of whatever the RCA method already decided.
ENABLE_AGENT_SYNTHESIS = os.environ.get("ENABLE_AGENT_SYNTHESIS") == "1"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _rank_of(ranked_nodes: list[str], root_cause: str) -> int | None:
    if root_cause in ranked_nodes:
        return ranked_nodes.index(root_cause) + 1
    return None


def _write_result_file(run: BenchmarkRun, scenario: Scenario) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{run.scenario_id}__{run.id}.json"
    if path.exists():
        raise FileExistsError(f"result file already exists, refusing to overwrite: {path}")
    payload = {
        "run": run.model_dump(mode="json"),
        "scenario": scenario.model_dump(mode="json"),
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


async def _run_scenario_async(
    scenario_id: str,
    method: str = "graph_only",
    events_per_second: float = 10.0,
) -> BenchmarkRun:
    scenario = load_scenario(scenario_id)
    started_at = datetime.now(timezone.utc)
    logger.info(f"starting benchmark run for scenario={scenario_id} method={method}")

    stop_event = asyncio.Event()
    workload_task = asyncio.create_task(
        run_workload(scenario.seed, EVENT_API_URL, stop_event, events_per_second)
    )

    await asyncio.sleep(scenario.inject_at_seconds)

    injector = get_injector(scenario.fault)
    await injector.enable()
    fault_injected_at = datetime.now(timezone.utc)
    logger.info(f"fault '{scenario.fault}' enabled for scenario {scenario_id}")

    await asyncio.sleep(POST_INJECT_SETTLE_SECONDS)

    incident = Incident(
        started_at=fault_injected_at,
        symptom_nodes=scenario.symptom_nodes,
        trigger_signal=scenario.fault,
        scenario_id=scenario.id,
    )
    IncidentRepository().create(incident)

    graph = build_reference_topology()
    rca_method = get_method(method, graph)

    intervention_scores: dict[str, float] = {}
    intervention_evidence: list = []
    intervention_testing_used = False
    if isinstance(rca_method, CauseGraphMethod) and ALLOW_INTERVENTION_TESTS:
        intervention_scores, intervention_evidence = await run_intervention_test(
            incident, recovery_window_seconds=INTERVENTION_RECOVERY_SECONDS
        )
        if intervention_scores:
            rca_method.intervention_scorer = lambda node_id, _inc: intervention_scores.get(
                node_id, 0.0
            )
            intervention_testing_used = True

    diagnosis_start = datetime.now(timezone.utc)
    hypotheses, evidence = rca_method.investigate(
        incident, incident_window=timedelta(seconds=POST_INJECT_SETTLE_SECONDS)
    )
    diagnosis_end = datetime.now(timezone.utc)
    evidence = evidence + intervention_evidence
    for ev in intervention_evidence:
        for h in hypotheses:
            if h.candidate_node == ev.candidate_node:
                h.evidence_ids.append(ev.id)

    EvidenceRepository().save_many(evidence)
    HypothesisRepository().save_many(hypotheses)
    IncidentRepository().update_status(incident.id, "diagnosed")

    agent_report = None
    if ENABLE_AGENT_SYNTHESIS:
        agent = InvestigatorAgent(AgentTools(graph=graph))
        agent_report = agent.investigate(incident, hypotheses, evidence)
        logger.info(f"agent synthesis: root_cause={agent_report.root_cause.node_id}")

    await injector.disable()
    logger.info(f"fault '{scenario.fault}' disabled (cleanup: {scenario.cleanup})")

    stop_event.set()
    await workload_task

    ranked_nodes = [h.candidate_node for h in sorted(hypotheses, key=lambda h: h.rank)]
    rank_of_truth = _rank_of(ranked_nodes, scenario.root_cause)
    finished_at = datetime.now(timezone.utc)

    run = BenchmarkRun(
        git_sha=_git_sha(),
        scenario_id=scenario.id,
        scenario_version=scenario_version(scenario.id),
        seed=scenario.seed,
        workload_config={"events_per_second": events_per_second},
        method=method,
        method_config={
            "intervention_testing": intervention_testing_used,
            "agent_synthesis": agent_report is not None,
        },
        started_at=started_at,
        finished_at=finished_at,
        metrics={
            "top1_accuracy": bool(ranked_nodes) and ranked_nodes[0] == scenario.root_cause,
            "top3_accuracy": scenario.root_cause in ranked_nodes[:3],
            "mrr": (1.0 / rank_of_truth) if rank_of_truth else 0.0,
            "rank_of_ground_truth": rank_of_truth,
            "intervention_scores": intervention_scores,
            "time_to_diagnosis_seconds": (diagnosis_end - diagnosis_start).total_seconds(),
            "ranked_candidates": ranked_nodes,
            "incident_id": incident.id,
            "agent_report": agent_report.model_dump(mode="json") if agent_report else None,
        },
    )
    BenchmarkRunRepository().save(run)
    result_path = _write_result_file(run, scenario)
    logger.info(f"benchmark run {run.id} complete; result saved to {result_path}")
    return run


def run_scenario(
    scenario_id: str, method: str = "graph_only", events_per_second: float = 10.0
) -> BenchmarkRun:
    return asyncio.run(_run_scenario_async(scenario_id, method, events_per_second))


def compare_methods(
    scenario_id: str, methods: list[str] | None = None, events_per_second: float = 10.0
) -> list[BenchmarkRun]:
    """Run every given method against the same scenario, one independent
    fault-injection replay per method (spec section 9: baselines are
    compared "through the same evaluator"). Returns runs in method order."""
    from benchmark.baselines import list_methods

    methods = methods or list_methods()
    runs = []
    for method in methods:
        logger.info(f"comparing methods: running '{method}' on scenario={scenario_id}")
        runs.append(run_scenario(scenario_id, method=method, events_per_second=events_per_second))
    return runs
