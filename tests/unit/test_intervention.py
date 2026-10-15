from causegraph.causal.intervention import measure_intervention_effect


def test_drop_direction_recovery_scores_high_when_value_rises_back():
    # quality_proxy_score-style metric: low is bad, recovery means it rises.
    result = measure_intervention_effect(before=0.1, after=0.9, direction="drop")
    assert result.score > 0.9
    assert result.recovered


def test_spike_direction_recovery_scores_high_when_value_falls_back():
    # latency-style metric: high is bad, recovery means it falls.
    result = measure_intervention_effect(before=900.0, after=50.0, direction="spike")
    assert result.score > 0.9
    assert result.recovered


def test_no_improvement_scores_zero_and_is_not_recovered():
    result = measure_intervention_effect(before=900.0, after=950.0, direction="spike")
    assert result.score == 0.0
    assert not result.recovered


def test_getting_worse_in_drop_direction_scores_zero():
    result = measure_intervention_effect(before=0.5, after=0.1, direction="drop")
    assert result.score == 0.0
    assert not result.recovered


def test_handles_zero_before_value_without_crashing():
    result = measure_intervention_effect(before=0.0, after=5.0, direction="drop")
    assert 0.0 <= result.score <= 1.0
