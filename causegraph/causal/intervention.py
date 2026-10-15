"""Intervention/counterfactual evidence math (spec section 5.3): "If the
system suspects component c, the harness can restore c... while holding
other conditions fixed. If downstream symptoms disappear consistently,
causal confidence increases."

This module is deliberately domain-agnostic -- it just scores a before/after
measurement. It knows nothing about fault injectors, Kafka, or which node
owns which fault; that orchestration (which genuinely requires
benchmark-only privileges, per spec section 6.1: "request_intervention_test
- benchmark/dev mode only") lives in
benchmark/evaluator/intervention_runner.py. Keeping this module dependency-
free means causegraph/ never depends on benchmark/, preserving the layering
from docs/adr/0003-graph-repository-interface.md's spirit: core logic
behind a narrow interface, orchestration above it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class InterventionResult:
    before_value: float
    after_value: float
    direction: Literal["spike", "drop"]
    score: float  # 0 (no recovery) .. 1 (full recovery), interpretable, not a probability
    recovered: bool


def measure_intervention_effect(
    before: float,
    after: float,
    direction: Literal["spike", "drop"],
    recovery_threshold: float = 0.5,
) -> InterventionResult:
    """Score how much a symptom metric moved toward "healthy" after an
    intervention. `direction` matches the symptom's own anomaly direction
    (NodeSignal.direction): "drop" means low is bad (e.g. quality proxy),
    so recovery means the value went up; "spike" means high is bad (e.g.
    latency), so recovery means the value went down.
    """
    delta = (after - before) if direction == "drop" else (before - after)

    magnitude = abs(before) if before != 0 else (abs(after) or 1.0)
    score = max(0.0, min(1.0, delta / magnitude))

    return InterventionResult(
        before_value=before,
        after_value=after,
        direction=direction,
        score=score,
        recovered=score >= recovery_threshold,
    )
