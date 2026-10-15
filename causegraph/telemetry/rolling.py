"""Sliding-window rate tracker used by services for in-process health
signals (error rate, null-feature rate, ...) that get exported as
Prometheus gauges. See causegraph/rca/node_signals.py for how these signals
are consumed by the RCA baseline.
"""

from __future__ import annotations

import time
from collections import deque


class RollingRate:
    def __init__(self, window_seconds: float = 30.0) -> None:
        self.window_seconds = window_seconds
        self._events: deque[tuple[float, bool]] = deque()

    def record(self, outcome: bool) -> None:
        now = time.monotonic()
        self._events.append((now, outcome))
        self._evict(now)

    def rate(self) -> float:
        self._evict(time.monotonic())
        if not self._events:
            return 0.0
        true_count = sum(1 for _, outcome in self._events if outcome)
        return true_count / len(self._events)

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
