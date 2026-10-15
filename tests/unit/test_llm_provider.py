from causegraph.llm.provider import CandidateContext, DeterministicMockProvider


def test_mock_provider_ranks_strongest_signal_first():
    provider = DeterministicMockProvider()
    candidates = [
        CandidateContext(node_id="quiet-node", node_type="service", raw_signals={"latency_ms": 5.0}),
        CandidateContext(
            node_id="loud-node", node_type="service", raw_signals={"latency_ms": 900.0}
        ),
    ]
    result = provider.rank_candidates("test incident", candidates)
    assert result.ranked_node_ids[0] == "loud-node"
    assert result.provider_name == "mock"
    assert 0.0 <= result.confidence <= 1.0


def test_mock_provider_rewards_recent_changes():
    provider = DeterministicMockProvider()
    candidates = [
        CandidateContext(node_id="no-change", node_type="service", raw_signals={"x": 1.0}),
        CandidateContext(
            node_id="has-change",
            node_type="service",
            raw_signals={"x": 1.0},
            recent_changes=["schema change at t0"],
        ),
    ]
    result = provider.rank_candidates("test incident", candidates)
    assert result.ranked_node_ids[0] == "has-change"
    assert "schema change" in result.rationale["has-change"]


def test_mock_provider_handles_no_candidates():
    provider = DeterministicMockProvider()
    result = provider.rank_candidates("test incident", [])
    assert result.ranked_node_ids == []
    assert result.confidence == 0.0
