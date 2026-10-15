from datetime import datetime, timedelta

from causegraph.anomalies.detector import RobustZScoreDetector


class FakePrometheusClient:
    def __init__(self, baseline_values: list[float], incident_values: list[float]) -> None:
        self.baseline_values = baseline_values
        self.incident_values = incident_values
        self.calls: list[tuple] = []

    def query_range(self, promql, start, end, step_seconds=5):
        self.calls.append((promql, start, end))
        values = self.incident_values if start >= self._boundary else self.baseline_values
        return [(start.timestamp() + i, v) for i, v in enumerate(values)]

    _boundary = datetime(2026, 1, 1, 0, 10)


def test_robust_zscore_flags_a_spike():
    client = FakePrometheusClient(baseline_values=[1.0, 1.1, 0.9, 1.0, 1.05], incident_values=[50.0])
    detector = RobustZScoreDetector(prometheus=client)
    incident_start = datetime(2026, 1, 1, 0, 10)
    result = detector.score(
        "model-service", "fake_query", incident_start, incident_start + timedelta(minutes=1)
    )
    assert result.has_data
    assert result.severity > 3.0


def test_robust_zscore_is_quiet_when_stable():
    client = FakePrometheusClient(baseline_values=[1.0, 1.0, 1.0, 1.0], incident_values=[1.02])
    detector = RobustZScoreDetector(prometheus=client)
    incident_start = datetime(2026, 1, 1, 0, 10)
    result = detector.score(
        "model-service", "fake_query", incident_start, incident_start + timedelta(minutes=1)
    )
    assert result.has_data
    assert result.severity < 1.0


def test_robust_zscore_handles_drop_direction():
    client = FakePrometheusClient(baseline_values=[0.8, 0.82, 0.79, 0.81], incident_values=[0.1])
    detector = RobustZScoreDetector(prometheus=client)
    incident_start = datetime(2026, 1, 1, 0, 10)
    result = detector.score(
        "quality-monitor",
        "fake_query",
        incident_start,
        incident_start + timedelta(minutes=1),
        direction="drop",
    )
    assert result.has_data
    assert result.severity > 3.0


def test_no_data_returns_zero_severity():
    client = FakePrometheusClient(baseline_values=[], incident_values=[])
    detector = RobustZScoreDetector(prometheus=client)
    incident_start = datetime(2026, 1, 1, 0, 10)
    result = detector.score(
        "model-service", "fake_query", incident_start, incident_start + timedelta(minutes=1)
    )
    assert not result.has_data
    assert result.severity == 0.0
