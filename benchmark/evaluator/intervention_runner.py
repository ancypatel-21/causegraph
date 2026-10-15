"""Orchestrates a real intervention test against the live stack: measure
the symptom, disable the candidate's owned fault, wait, re-measure,
restore the fault. This is the "benchmark/dev mode only" privilege spec
section 6.1 reserves for `request_intervention_test` -- it is never
exposed over the causegraph-api HTTP surface or any agent tool; only the
benchmark evaluator calls it, and only when explicitly enabled.
"""

from __future__ import annotations

import asyncio

from causegraph.anomalies.prometheus_client import PrometheusClient
from causegraph.causal import InterventionResult, measure_intervention_effect
from causegraph.graph.topology import EVENT_STREAM, FEATURE_WORKER, MODEL_SERVICE
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.schemas import Evidence, Incident
from causegraph.telemetry import get_logger

from benchmark.injectors import get_injector

logger = get_logger("benchmark-evaluator")

# Which node a given fault *type* can actually be toggled on -- this is a
# property of our own testbed's levers, known the same way the evaluator
# already knows which injector to call for cleanup. It is not the ground
# truth answer: a real on-call engineer knows what they can revert without
# knowing in advance whether reverting it will fix anything.
FAULT_OWNER_NODE: dict[str, str] = {
    "incompatible_schema": FEATURE_WORKER,
    "latency": MODEL_SERVICE,
    "consumer_lag": EVENT_STREAM,
}


async def run_intervention_test(
    incident: Incident,
    recovery_window_seconds: float = 10.0,
    prometheus: PrometheusClient | None = None,
) -> tuple[dict[str, float], list[Evidence]]:
    """Returns ({node_id: I(c) score}, [Evidence]). Empty if there is no
    known lever for this incident's active fault, or no telemetry to judge
    recovery by -- intervention evidence is sparse by nature (spec section
    5.3: "when available"), never fabricated when unavailable.
    """
    owner_node = FAULT_OWNER_NODE.get(incident.trigger_signal)
    if owner_node is None:
        return {}, []

    symptom_node = incident.symptom_nodes[0] if incident.symptom_nodes else None
    signal = NODE_SIGNALS.get(symptom_node) if symptom_node else None
    if signal is None:
        return {}, []

    prometheus = prometheus or PrometheusClient()
    before = prometheus.query(signal.query)
    if before is None:
        return {}, []

    injector = get_injector(incident.trigger_signal)
    logger.info(f"intervention test: disabling '{incident.trigger_signal}' to probe {owner_node}")
    await injector.disable()
    try:
        await asyncio.sleep(recovery_window_seconds)
        after = prometheus.query(signal.query)
    finally:
        # Always restore -- the scenario's own cleanup still runs later,
        # but the fault must stay "active" for the rest of the incident
        # window regardless of what this probe finds.
        await injector.enable()
        logger.info(f"intervention test: restored '{incident.trigger_signal}'")

    if after is None:
        return {}, []

    result: InterventionResult = measure_intervention_effect(before, after, signal.direction)
    evidence = Evidence(
        incident_id=incident.id,
        candidate_node=owner_node,
        evidence_type="intervention_test",
        source="benchmark-harness",
        observed_at=incident.started_at,
        value={
            "before": result.before_value,
            "after": result.after_value,
            "fault": incident.trigger_signal,
        },
        reliability=0.95,  # the strongest evidence type available (spec section 5.3)
        supports=result.recovered,
    )
    return {owner_node: result.score}, [evidence]
