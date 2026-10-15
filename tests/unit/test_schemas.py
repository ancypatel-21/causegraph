from datetime import datetime

import pytest
from pydantic import ValidationError

from causegraph.schemas import Evidence, Hypothesis, Incident, Scenario


def test_incident_defaults_id_and_status():
    incident = Incident(
        started_at=datetime(2026, 1, 1), symptom_nodes=["ranking-api"], trigger_signal="latency"
    )
    assert incident.id.startswith("inc-")
    assert incident.status.value == "open"


def test_evidence_reliability_must_be_in_unit_interval():
    with pytest.raises(ValidationError):
        Evidence(
            incident_id="inc-1",
            candidate_node="feature-worker",
            evidence_type="temporal_anomaly",
            source="prometheus",
            observed_at=datetime(2026, 1, 1),
            reliability=1.5,
            supports=True,
        )


def test_hypothesis_round_trips_through_json():
    hypothesis = Hypothesis(
        incident_id="inc-1",
        candidate_node="feature-worker",
        rank=1,
        score=0.9,
        causal_path=["feature-worker", "model-service"],
    )
    restored = Hypothesis.model_validate_json(hypothesis.model_dump_json())
    assert restored == hypothesis


def test_scenario_matches_manifest_schema():
    scenario = Scenario(
        id="data-schema-001",
        seed=42,
        root_cause="feature-worker",
        fault="incompatible_schema",
        inject_at_seconds=45,
        symptom_nodes=["model-service", "ranking-api"],
        expected_path=["feature-worker", "feature-store", "model-service"],
        cleanup="restore_schema",
        severity="medium",
        labels=["data", "schema"],
    )
    assert scenario.root_cause in scenario.expected_path
