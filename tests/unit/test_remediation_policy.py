from causegraph.graph.topology import EVENT_STREAM, FEATURE_STORE, FEATURE_WORKER
from causegraph.remediation.policy import PolicyEngine
from causegraph.schemas import RiskTier


def test_medium_risk_action_is_allowed_but_requires_approval():
    decision = PolicyEngine().evaluate("restore_schema", FEATURE_WORKER)
    assert decision.allowed
    assert decision.requires_approval
    assert decision.risk_tier == RiskTier.MEDIUM


def test_low_risk_action_is_allowed_without_approval():
    decision = PolicyEngine().evaluate("resume_consumer", EVENT_STREAM)
    assert decision.allowed
    assert not decision.requires_approval
    assert decision.risk_tier == RiskTier.LOW


def test_high_risk_action_is_always_denied():
    decision = PolicyEngine().evaluate("drop_database", FEATURE_STORE)
    assert not decision.allowed
    assert decision.risk_tier == RiskTier.HIGH
    assert "disallowed" in decision.reason


def test_unknown_action_target_pair_is_denied():
    decision = PolicyEngine().evaluate("not_a_real_action", "not_a_real_node")
    assert not decision.allowed
    assert decision.risk_tier is None
    assert "not an allow-listed" in decision.reason


def test_action_valid_for_one_target_is_not_valid_for_another():
    # restore_schema is only allow-listed for feature-worker, not for an
    # arbitrary other node -- the allow-list is (action_type, target) pairs,
    # not just action_type.
    decision = PolicyEngine().evaluate("restore_schema", EVENT_STREAM)
    assert not decision.allowed
