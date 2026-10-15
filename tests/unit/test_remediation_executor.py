import pytest

from causegraph.graph.topology import EVENT_STREAM, FEATURE_STORE, FEATURE_WORKER
from causegraph.remediation.executor import RemediationError, RemediationExecutor
from causegraph.schemas import RemediationStatus


class FakeRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, object] = {}

    def create(self, proposal):
        self.by_id[proposal.id] = proposal
        return proposal

    def get(self, proposal_id):
        return self.by_id.get(proposal_id)

    def get_by_idempotency_key(self, key):
        return next((p for p in self.by_id.values() if p.idempotency_key == key), None)

    def save(self, proposal):
        self.by_id[proposal.id] = proposal
        return proposal


class FakePrometheusClient:
    def query(self, promql):
        return 1.0


class FakeAsyncClient:
    calls: list[tuple[str, dict]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json):
        FakeAsyncClient.calls.append((url, json))
        return None


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    import causegraph.remediation.executor as executor_module

    FakeAsyncClient.calls = []
    monkeypatch.setattr(executor_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("FEATURE_WORKER_URL", "http://feature-worker:8002")
    monkeypatch.setenv("MODEL_SERVICE_URL", "http://model-service:8003")


def _executor() -> RemediationExecutor:
    return RemediationExecutor(repo=FakeRepo(), prometheus=FakePrometheusClient())


def test_propose_an_allowed_action_is_proposed_not_rejected():
    executor = _executor()
    proposal = executor.propose("inc-1", "restore_schema", FEATURE_WORKER)
    assert proposal.status == RemediationStatus.PROPOSED


def test_propose_a_high_risk_action_is_rejected_outright():
    executor = _executor()
    proposal = executor.propose("inc-1", "drop_database", FEATURE_STORE)
    assert proposal.status == RemediationStatus.REJECTED


def test_propose_is_idempotent_for_the_same_incident_action_target():
    executor = _executor()
    first = executor.propose("inc-1", "restore_schema", FEATURE_WORKER)
    second = executor.propose("inc-1", "restore_schema", FEATURE_WORKER)
    assert first.id == second.id


def test_approve_requires_proposed_status():
    executor = _executor()
    proposal = executor.propose("inc-1", "restore_schema", FEATURE_WORKER)
    approved = executor.approve(proposal.id, "oncall-engineer")
    assert approved.status == RemediationStatus.APPROVED
    assert approved.approved_by == "oncall-engineer"

    with pytest.raises(RemediationError):
        executor.approve(proposal.id, "oncall-engineer")  # already approved


@pytest.mark.asyncio
async def test_execute_medium_risk_without_approval_is_blocked():
    executor = _executor()
    proposal = executor.propose("inc-1", "restore_schema", FEATURE_WORKER)
    with pytest.raises(RemediationError):
        await executor.execute(proposal.id)
    assert FakeAsyncClient.calls == []


@pytest.mark.asyncio
async def test_execute_medium_risk_after_approval_calls_the_real_endpoint():
    executor = _executor()
    proposal = executor.propose("inc-1", "restore_schema", FEATURE_WORKER)
    executor.approve(proposal.id, "oncall-engineer")

    executed = await executor.execute(proposal.id)

    assert executed.status == RemediationStatus.EXECUTED
    assert FakeAsyncClient.calls == [
        ("http://feature-worker:8002/admin/fault/schema", {"enabled": False})
    ]


@pytest.mark.asyncio
async def test_execute_low_risk_does_not_require_approval():
    executor = _executor()
    proposal = executor.propose("inc-1", "resume_consumer", EVENT_STREAM)

    executed = await executor.execute(proposal.id)

    assert executed.status == RemediationStatus.EXECUTED


@pytest.mark.asyncio
async def test_execute_is_idempotent_no_double_execution():
    executor = _executor()
    proposal = executor.propose("inc-1", "resume_consumer", EVENT_STREAM)

    await executor.execute(proposal.id)
    await executor.execute(proposal.id)

    assert len(FakeAsyncClient.calls) == 1  # second execute() was a no-op


@pytest.mark.asyncio
async def test_rollback_requires_executed_status():
    executor = _executor()
    proposal = executor.propose("inc-1", "resume_consumer", EVENT_STREAM)
    with pytest.raises(RemediationError):
        await executor.rollback(proposal.id)


@pytest.mark.asyncio
async def test_rollback_calls_the_undo_payload():
    executor = _executor()
    proposal = executor.propose("inc-1", "resume_consumer", EVENT_STREAM)
    await executor.execute(proposal.id)

    rolled_back = await executor.rollback(proposal.id)

    assert rolled_back.status == RemediationStatus.ROLLED_BACK
    assert FakeAsyncClient.calls[-1] == ("http://feature-worker:8002/admin/fault/lag", {"enabled": True})


@pytest.mark.asyncio
async def test_cannot_execute_a_rejected_proposal():
    executor = _executor()
    proposal = executor.propose("inc-1", "drop_database", FEATURE_STORE)
    with pytest.raises(RemediationError):
        await executor.execute(proposal.id)


def test_audit_log_records_every_lifecycle_step():
    executor = _executor()
    proposal = executor.propose("inc-1", "restore_schema", FEATURE_WORKER)
    approved = executor.approve(proposal.id, "oncall-engineer")

    events = [entry["event"] for entry in approved.audit_log]
    assert events == ["proposed", "approved"]
