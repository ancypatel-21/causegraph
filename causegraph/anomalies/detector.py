"""Robust z-score anomaly detector. Spec section 3.1: "Robust z-score/EWMA
first; optional ML detector later." We start with the simpler, more
interpretable of the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np

from causegraph.anomalies.prometheus_client import PrometheusClient

# 1.4826 converts MAD to a scale comparable to the standard deviation for a
# normal distribution; 0.6745 is the standard robust z-score normalizer.
_MAD_CONSTANT = 1.4826


@dataclass
class AnomalyResult:
    node_id: str
    metric_query: str
    severity: float  # 0.0 (normal) upward; unbounded, but >3 is a strong signal
    baseline_median: float
    incident_value: float
    has_data: bool


class RobustZScoreDetector:
    def __init__(self, prometheus: PrometheusClient | None = None) -> None:
        self.prometheus = prometheus or PrometheusClient()

    def score(
        self,
        node_id: str,
        metric_query: str,
        incident_start: datetime,
        incident_end: datetime,
        baseline_lookback: timedelta = timedelta(minutes=10),
        direction: Literal["spike", "drop"] = "spike",
    ) -> AnomalyResult:
        baseline_start = incident_start - baseline_lookback
        baseline_samples = self.prometheus.query_range(metric_query, baseline_start, incident_start)
        incident_samples = self.prometheus.query_range(metric_query, incident_start, incident_end)

        if not baseline_samples or not incident_samples:
            return AnomalyResult(
                node_id=node_id,
                metric_query=metric_query,
                severity=0.0,
                baseline_median=0.0,
                incident_value=0.0,
                has_data=False,
            )

        baseline_values = np.array([v for _, v in baseline_samples])
        incident_values = np.array([v for _, v in incident_samples])

        median = float(np.median(baseline_values))
        mad = float(np.median(np.abs(baseline_values - median)))
        incident_peak = (
            float(np.max(incident_values))
            if direction == "spike"
            else float(np.min(incident_values))
        )

        if mad == 0.0:
            # No variance in the baseline: any deviation at all is meaningful.
            severity = abs(incident_peak - median) * 10.0 if incident_peak != median else 0.0
        else:
            robust_std = mad * _MAD_CONSTANT
            severity = abs(incident_peak - median) / robust_std

        return AnomalyResult(
            node_id=node_id,
            metric_query=metric_query,
            severity=max(0.0, severity),
            baseline_median=median,
            incident_value=incident_peak,
            has_data=True,
        )
