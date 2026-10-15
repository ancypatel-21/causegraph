from datetime import datetime

import pytest

from causegraph.graph.topology import FEATURE_WORKER, QUALITY_MONITOR
from causegraph.schemas import Incident

from benchmark.evaluator import intervention_runner


class FakeInjector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def enable(self) -> None:
        self.calls.append("enable")

    async def disable(self) -> None:
        self.calls.append("disable")


class FakePrometheusClient:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def query(self, promql: str) -> float | None:
        return next(self._values, None)


def _incident(trigger_signal: str, symptom_nodes: list[str]) -> Incident:
    return Incident(
        started_at=datetime(2026, 1, 1), symptom_nodes=symptom_nodes, trigger_signal=trigger_signal
    )


@pytest.mark.asyncio
async def test_successful_recovery_produces_score_and_evidence(monkeypatch):
    injector = FakeInjector()
    monkeypatch.setattr(intervention_runner, "get_injector", lambda fault: injector)

    incident = _incident("incompatible_schema", [QUALITY_MONITOR])
    prometheus = FakePrometheusClient(values=[0.05, 0.9])  # before, after

    scores, evidence = await intervention_runner.run_intervention_test(
        incident, recovery_window_seconds=0.01, prometheus=prometheus
    )

    assert scores[FEATURE_WORKER] > 0.5
    assert injector.calls == ["disable", "enable"]
    assert len(evidence) == 1
    assert evidence[0].candidate_node == FEATURE_WORKER
    assert evidence[0].evidence_type == "intervention_test"
    assert evidence[0].supports is True


@pytest.mark.asyncio
async def test_restores_fault_even_if_measurement_fails(monkeypatch):
    injector = FakeInjector()
    monkeypatch.setattr(intervention_runner, "get_injector", lambda fault: injector)

    incident = _incident("incompatible_schema", [QUALITY_MONITOR])
    # First query (before) succeeds, second (after) returns None.
    prometheus = FakePrometheusClient(values=[0.05])

    scores, evidence = await intervention_runner.run_intervention_test(
        incident, recovery_window_seconds=0.01, prometheus=prometheus
    )

    assert scores == {}
    assert evidence == []
    assert injector.calls == ["disable", "enable"]  # always restored


@pytest.mark.asyncio
async def test_no_lever_known_for_fault_returns_nothing(monkeypatch):
    called = False

    def fail_if_called(fault):
        nonlocal called
        called = True
        raise AssertionError("should not look up an injector with no known lever")

    monkeypatch.setattr(intervention_runner, "get_injector", fail_if_called)

    incident = _incident("some_future_fault_type", [QUALITY_MONITOR])
    scores, evidence = await intervention_runner.run_intervention_test(
        incident, recovery_window_seconds=0.01, prometheus=FakePrometheusClient([])
    )

    assert scores == {}
    assert evidence == []
    assert not called
