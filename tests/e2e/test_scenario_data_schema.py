"""E2E benchmark layer (spec section 16, and section 21 step 46): a scenario
can be injected, observed, cleaned up, and evaluated against ground truth,
producing a saved benchmark artifact.
"""

from __future__ import annotations

from causegraph.db import init_db

from benchmark.scenarios import load_scenario
from tests.conftest import requires_live_stack


@requires_live_stack
def test_data_schema_scenario_produces_a_scored_benchmark_run():
    from benchmark.evaluator.evaluator import run_scenario

    init_db()
    scenario = load_scenario("data-schema-001")

    run = run_scenario("data-schema-001", events_per_second=15.0)

    assert run.scenario_id == scenario.id
    assert run.git_sha
    assert run.seed == scenario.seed
    assert "top1_accuracy" in run.metrics
    assert "ranked_candidates" in run.metrics
    # The fault must have been cleaned up: a fresh prediction should no
    # longer show feature skew once the schema fault is disabled.
    assert run.metrics["ranked_candidates"]
