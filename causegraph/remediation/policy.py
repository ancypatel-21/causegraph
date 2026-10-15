"""Deterministic remediation policy engine (spec section 11): "The LLM
proposes a typed action; a deterministic policy engine decides whether it
is allowed and whether human approval is required."

`ALLOWED_ACTIONS` is the allow-list spec section 11 requires ("Allow-list
action types and targets."). Every entry's `action_type` is one of the
scenario `cleanup` values already defined in benchmark/scenarios/*.yaml --
remediation actions are literally "undo the fault," the same mechanism
the benchmark harness already uses for cleanup, just gated by policy
instead of running unconditionally.

HIGH risk actions are never executable, full stop (spec section 11:
"database mutation; destructive command; arbitrary shell -- Disallowed
in project"). This is enforced here, not just documented -- see
test_remediation_policy.py for the concrete denial.
"""

from __future__ import annotations

from dataclasses import dataclass

from causegraph.graph.topology import EVENT_STREAM, FEATURE_STORE, FEATURE_WORKER, MODEL_SERVICE
from causegraph.schemas import RiskTier


@dataclass(frozen=True)
class ActionDefinition:
    risk_tier: RiskTier
    service_url_env: str  # which env var names the service to call
    endpoint: str
    # What the HTTP body looks like to apply the fix vs. to undo the fix.
    # Fixed, hand-authored payloads -- never built from free-form text
    # (spec section 11: "Never interpolate free-form LLM text into shell
    # commands," generalized here to "into any request body").
    fix_payload: dict
    undo_payload: dict
    health_signal_node: str


ALLOWED_ACTIONS: dict[tuple[str, str], ActionDefinition] = {
    ("restore_schema", FEATURE_WORKER): ActionDefinition(
        risk_tier=RiskTier.MEDIUM,
        service_url_env="FEATURE_WORKER_URL",
        endpoint="/admin/fault/schema",
        fix_payload={"enabled": False},
        undo_payload={"enabled": True},
        health_signal_node=FEATURE_WORKER,
    ),
    ("restore_ttl", FEATURE_WORKER): ActionDefinition(
        risk_tier=RiskTier.MEDIUM,
        service_url_env="FEATURE_WORKER_URL",
        endpoint="/admin/fault/ttl",
        fix_payload={"enabled": False},
        undo_payload={"enabled": True},
        health_signal_node=FEATURE_WORKER,
    ),
    ("resume_consumer", EVENT_STREAM): ActionDefinition(
        risk_tier=RiskTier.LOW,
        service_url_env="FEATURE_WORKER_URL",
        endpoint="/admin/fault/lag",
        fix_payload={"enabled": False},
        undo_payload={"enabled": True},
        health_signal_node=EVENT_STREAM,
    ),
    ("restore_latency", MODEL_SERVICE): ActionDefinition(
        risk_tier=RiskTier.MEDIUM,
        service_url_env="MODEL_SERVICE_URL",
        endpoint="/admin/fault/latency",
        fix_payload={"enabled": False},
        undo_payload={"enabled": True, "latency_ms": 500.0},
        health_signal_node=MODEL_SERVICE,
    ),
    ("restore_redis", FEATURE_STORE): ActionDefinition(
        risk_tier=RiskTier.MEDIUM,
        service_url_env="MODEL_SERVICE_URL",
        endpoint="/admin/fault/redis-unavailable",
        fix_payload={"enabled": False},
        undo_payload={"enabled": True},
        health_signal_node=FEATURE_STORE,
    ),
    # Illustrative only -- proves HIGH-risk actions are denied in code,
    # not just in prose. No executor path ever reads this entry's
    # payloads; evaluate() rejects it before execution is possible.
    ("drop_database", FEATURE_STORE): ActionDefinition(
        risk_tier=RiskTier.HIGH,
        service_url_env="",
        endpoint="",
        fix_payload={},
        undo_payload={},
        health_signal_node=FEATURE_STORE,
    ),
}


# Which allow-listed action_type fixes a given fault *type* -- lets the
# investigator agent (causegraph/agent/investigator.py) recommend a real,
# allow-listed action instead of a generic placeholder, using the same
# signal (incident.trigger_signal) the benchmark harness already uses to
# know which injector to call.
FAULT_TO_ACTION_TYPE: dict[str, str] = {
    "incompatible_schema": "restore_schema",
    "cache_ttl_regression": "restore_ttl",
    "consumer_lag": "resume_consumer",
    "latency": "restore_latency",
    "redis_unavailable": "restore_redis",
}


@dataclass
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    risk_tier: RiskTier | None
    reason: str
    action_def: ActionDefinition | None = None


class PolicyEngine:
    def evaluate(self, action_type: str, target: str) -> PolicyDecision:
        action_def = ALLOWED_ACTIONS.get((action_type, target))

        if action_def is None:
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                risk_tier=None,
                reason=f"'{action_type}' on '{target}' is not an allow-listed action/target pair",
            )

        if action_def.risk_tier == RiskTier.HIGH:
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                risk_tier=RiskTier.HIGH,
                reason="high-risk actions are disallowed in this project (spec section 11)",
                action_def=action_def,
            )

        if action_def.risk_tier == RiskTier.LOW:
            return PolicyDecision(
                allowed=True,
                requires_approval=False,
                risk_tier=RiskTier.LOW,
                reason="low-risk action; may auto-execute in the benchmark sandbox",
                action_def=action_def,
            )

        return PolicyDecision(
            allowed=True,
            requires_approval=True,
            risk_tier=RiskTier.MEDIUM,
            reason="medium-risk action; requires explicit human approval before execution",
            action_def=action_def,
        )
