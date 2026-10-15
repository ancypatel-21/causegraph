"""Remediation executor (spec section 10/11): propose -> approve ->
execute, with idempotency keys and audit logs (spec section 11's
explicit requirements), and a rollback path for every executable
remediation.

This is the one place in the whole project that actually calls a
service's admin endpoint from *production* code (causegraph-api), as
opposed to the benchmark harness's fault injectors
(benchmark/injectors/). The two look mechanically similar (both POST
enabled:true/false to the same endpoints) but serve different roles:
injectors create ground-truth incidents for the benchmark; this executes
a policy-approved fix against a real diagnosed incident. Every request
this module sends is built from `ALLOWED_ACTIONS`' fixed payloads --
never from incident text, LLM output, or any other free-form input.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

import httpx

from causegraph.anomalies.prometheus_client import PrometheusClient
from causegraph.persistence import RemediationProposalRepository
from causegraph.rca.node_signals import NODE_SIGNALS
from causegraph.remediation.policy import PolicyEngine
from causegraph.schemas import RemediationProposal, RemediationStatus, RiskTier


class RemediationError(Exception):
    pass


def _idempotency_key(incident_id: str, action_type: str, target: str) -> str:
    raw = f"{incident_id}:{action_type}:{target}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _audit(event: str, actor: str, detail: dict | None = None) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "event": event,
        "detail": detail or {},
    }


class RemediationExecutor:
    def __init__(
        self,
        repo: RemediationProposalRepository | None = None,
        policy: PolicyEngine | None = None,
        prometheus: PrometheusClient | None = None,
    ) -> None:
        self.repo = repo or RemediationProposalRepository()
        self.policy = policy or PolicyEngine()
        self.prometheus = prometheus or PrometheusClient()

    def propose(self, incident_id: str, action_type: str, target: str) -> RemediationProposal:
        idempotency_key = _idempotency_key(incident_id, action_type, target)
        existing = self.repo.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing

        decision = self.policy.evaluate(action_type, target)
        proposal = RemediationProposal(
            incident_id=incident_id,
            action_type=action_type,
            target=target,
            risk_tier=decision.risk_tier or RiskTier.HIGH,
            status=RemediationStatus.PROPOSED if decision.allowed else RemediationStatus.REJECTED,
            idempotency_key=idempotency_key,
            reason=decision.reason,
            proposed_at=datetime.now(timezone.utc),
            audit_log=[_audit("proposed", "system", {"allowed": decision.allowed, "reason": decision.reason})],
        )
        return self.repo.create(proposal)

    def approve(self, proposal_id: str, approved_by: str) -> RemediationProposal:
        proposal = self._require(proposal_id)
        if proposal.status != RemediationStatus.PROPOSED:
            raise RemediationError(f"cannot approve a proposal in status '{proposal.status}'")

        proposal.status = RemediationStatus.APPROVED
        proposal.approved_by = approved_by
        proposal.approved_at = datetime.now(timezone.utc)
        proposal.audit_log.append(_audit("approved", approved_by))
        return self.repo.save(proposal)

    async def execute(self, proposal_id: str) -> RemediationProposal:
        proposal = self._require(proposal_id)

        if proposal.status == RemediationStatus.EXECUTED:
            return proposal  # idempotent: already done, no double execution

        if proposal.status == RemediationStatus.REJECTED:
            raise RemediationError("cannot execute a rejected proposal")

        if proposal.risk_tier == RiskTier.MEDIUM and proposal.status != RemediationStatus.APPROVED:
            raise RemediationError("medium-risk actions require approval before execution")

        decision = self.policy.evaluate(proposal.action_type, proposal.target)
        if not decision.allowed or decision.action_def is None:
            raise RemediationError(decision.reason)
        action_def = decision.action_def

        signal = NODE_SIGNALS.get(action_def.health_signal_node)
        before = self.prometheus.query(signal.query) if signal else None
        proposal.precondition_results = {"health_before": before}

        base_url = os.environ.get(action_def.service_url_env)
        if not base_url:
            raise RemediationError(f"{action_def.service_url_env} is not configured")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{base_url}{action_def.endpoint}", json=action_def.fix_payload)
        except Exception as exc:
            proposal.status = RemediationStatus.FAILED
            proposal.audit_log.append(_audit("execution_failed", "system", {"error": str(exc)}))
            self.repo.save(proposal)
            raise RemediationError(f"action execution failed: {exc}") from exc

        after = self.prometheus.query(signal.query) if signal else None
        proposal.post_action_health = {"health_after": after}
        proposal.status = RemediationStatus.EXECUTED
        proposal.executed_at = datetime.now(timezone.utc)
        proposal.audit_log.append(
            _audit("executed", "system", {"health_before": before, "health_after": after})
        )
        return self.repo.save(proposal)

    async def rollback(self, proposal_id: str) -> RemediationProposal:
        proposal = self._require(proposal_id)
        if proposal.status != RemediationStatus.EXECUTED:
            raise RemediationError("can only roll back an executed proposal")

        decision = self.policy.evaluate(proposal.action_type, proposal.target)
        if decision.action_def is None:
            raise RemediationError("no action definition found for rollback")
        action_def = decision.action_def

        base_url = os.environ.get(action_def.service_url_env)
        if not base_url:
            raise RemediationError(f"{action_def.service_url_env} is not configured")

        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{base_url}{action_def.endpoint}", json=action_def.undo_payload)

        proposal.status = RemediationStatus.ROLLED_BACK
        proposal.rolled_back_at = datetime.now(timezone.utc)
        proposal.audit_log.append(_audit("rolled_back", "system"))
        return self.repo.save(proposal)

    def _require(self, proposal_id: str) -> RemediationProposal:
        proposal = self.repo.get(proposal_id)
        if proposal is None:
            raise RemediationError(f"no remediation proposal '{proposal_id}'")
        return proposal
