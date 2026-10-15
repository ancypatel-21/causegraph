"""Common interface every RCA method (baselines B0-B4, and CauseGraph
itself) implements, so the evaluator can run any of them identically. Only
graph-only (B3) is implemented in Sprint 1 (spec section 21, step 45); the
rest are Phase 5 (spec section 13)."""

from __future__ import annotations

from typing import Protocol

from causegraph.schemas import Evidence, Hypothesis, Incident


class RcaMethod(Protocol):
    method_name: str

    def investigate(self, incident: Incident) -> tuple[list[Hypothesis], list[Evidence]]: ...
