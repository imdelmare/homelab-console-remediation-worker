import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from remediation_worker.config import Settings
from remediation_worker.gateway import GatewayError, LeasedGatewayProxy, McpHttpGateway
from remediation_worker.protocol import EngineResult, Job
from remediation_worker.runner import Runner


JOB = Job("job-1", "task-1", 3, "lease-secret", "2099-01-01T00:00:00Z", 1)


class FakeGateway:
    def __init__(self, status="completed", failures=0, renew_extension=.2):
        self.status, self.failures, self.renew_extension, self.calls = status, failures, renew_extension, []

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.failures:
            self.failures -= 1
            raise GatewayError("mcp_unavailable")
        if tool == "tasks_get":
            return {"status": self.status, "version": 4, "assigned_agent": "agent:worker:x"}
        if tool == "tasks_set_status":
            self.status = "blocked"
            return {"status": "blocked", "version": 5}
        if tool == "tasks_release":
            self.status = "open"
            return {"status": "open", "version": 5, "assigned_agent": None}
        if tool == "tasks_worker_renew":
            return {"job_id": "job-1", "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=self.renew_extension)).isoformat()}
        return {"job": None, "retry_after_seconds": 1}


class FakeEngine:
    def __init__(self, wait=False):
        self.wait, self.terminated, self.runs = wait, False, 0
        self.release = asyncio.Event()

    async def run(self, job, lease_file=None):
        self.runs += 1
        if self.wait:
            await self.release.wait()
        return EngineResult(exit_code=0)

    async def terminate(self):
        self.terminated = True
        self.release.set()


@pytest.mark.asyncio
async def test_completed_job_is_finished():
    gateway = FakeGateway()
    await Runner(gateway, FakeEngine()).run_job(JOB)
    finish = [args for tool, args in gateway.calls if tool == "tasks_worker_finish"]
    assert finish[0]["outcome"] == "completed"
    assert len(finish[0]["idempotency_key"]) == 36


@pytest.mark.asyncio
async def test_incomplete_job_is_blocked_then_failed():
    gateway = FakeGateway("investigating")
    await Runner(gateway, FakeEngine()).run_job(JOB)
    blocked = next(args for tool, args in gateway.calls if tool == "tasks_set_status")
    finish = next(args for tool, args in gateway.calls if tool == "tasks_worker_finish")
    assert blocked["task_id"] == JOB.task_id
    assert blocked["worker_job_id"] == JOB.job_id
    assert blocked["worker_lease_token"] == JOB.lease_token
    assert finish["outcome"] == "failed"
    assert finish["error_code"] == "engine_no_tool_calls"


@pytest.mark.asyncio
async def test_failed_tool_calls_preserve_only_normalized_error_code():
    class ToolFailureEngine(FakeEngine):
        async def run(self, job, lease_file=None):
            return EngineResult(
                exit_code=0,
                attempted_tool_calls=2,
                successful_tool_calls=0,
                last_error_code="worker_lease_stale",
            )

    gateway = FakeGateway("investigating")
    await Runner(gateway, ToolFailureEngine()).run_job(JOB)
    finish = next(args for tool, args in gateway.calls if tool == "tasks_worker_finish")
    assert finish["error_code"] == "worker_lease_stale"


@pytest.mark.asyncio
async def test_successful_tool_calls_without_completion_are_engine_incomplete():
    class PartialEngine(FakeEngine):
        async def run(self, job, lease_file=None):
            return EngineResult(exit_code=0, attempted_tool_calls=3, successful_tool_calls=2)

    gateway = FakeGateway("investigating")
    await Runner(gateway, PartialEngine()).run_job(JOB)
    finish = next(args for tool, args in gateway.calls if tool == "tasks_worker_finish")
    assert finish["error_code"] == "engine_incomplete"


@pytest.mark.asyncio
async def test_renewal_occurs_for_long_engine():
    gateway, engine = FakeGateway(renew_extension=1), FakeEngine(wait=True)
    short_job = Job("job-1", "task-1", 3, "lease-secret", (datetime.now(UTC) + timedelta(seconds=.2)).isoformat(), 1)
    task = asyncio.create_task(Runner(gateway, engine, lease_safety_seconds=.02).run_job(short_job))
    await asyncio.sleep(.15)
    engine.release.set()
    await task
    assert any(tool == "tasks_worker_renew" for tool, _ in gateway.calls)


@pytest.mark.asyncio
async def test_lease_loss_terminates_engine():
    gateway, engine = FakeGateway(failures=100), FakeEngine(wait=True)
    short_job = Job("job-1", "task-1", 3, "lease-secret", (datetime.now(UTC) + timedelta(seconds=.2)).isoformat(), 1)
    task = asyncio.create_task(Runner(gateway, engine, lease_safety_seconds=.02).run_job(short_job))
    await asyncio.sleep(.35)
    await task
    assert engine.terminated
    assert not any(tool in {"tasks_get", "tasks_worker_finish"} for tool, _ in gateway.calls)


@pytest.mark.asyncio
async def test_graceful_stop_terminates_engine_releases_and_finishes():
    gateway, engine = FakeGateway("investigating"), FakeEngine(wait=True)
    runner = Runner(gateway, engine)
    task = asyncio.create_task(runner.run_job(JOB))
    await asyncio.sleep(0.05)
    runner.stop()
    await task
    assert engine.terminated
    release = next(args for tool, args in gateway.calls if tool == "tasks_release")
    finish = next(args for tool, args in gateway.calls if tool == "tasks_worker_finish")
    assert release["worker_job_id"] == JOB.job_id
    assert finish["outcome"] == "released"


@pytest.mark.asyncio
async def test_claimed_task_moves_to_investigating_then_blocked():
    gateway = FakeGateway("claimed")
    await Runner(gateway, FakeEngine()).run_job(JOB)
    transitions = [args["status"] for tool, args in gateway.calls if tool == "tasks_set_status"]
    assert transitions == ["investigating", "blocked"]


@pytest.mark.asyncio
async def test_engine_exception_blocks_and_finishes_without_raw_output():
    class BrokenEngine(FakeEngine):
        async def run(self, job, lease_file=None):
            raise RuntimeError("provider secret output")
    gateway = FakeGateway("investigating")
    await Runner(gateway, BrokenEngine()).run_job(JOB)
    finish = next(args for tool, args in gateway.calls if tool == "tasks_worker_finish")
    assert finish["outcome"] == "retry"
    assert finish["error_code"] == "engine_exit_nonzero"
    assert not any(tool == "tasks_set_status" for tool, _ in gateway.calls)


@pytest.mark.asyncio
async def test_timeout_retries_without_mutating_active_task():
    class TimedOutEngine(FakeEngine):
        async def run(self, job, lease_file=None):
            return EngineResult(exit_code=124)

    gateway = FakeGateway("investigating")
    await Runner(gateway, TimedOutEngine()).run_job(JOB)
    finish = next(args for tool, args in gateway.calls if tool == "tasks_worker_finish")
    assert finish["outcome"] == "retry"
    assert finish["error_code"] == "engine_timeout"
    assert not any(tool == "tasks_set_status" for tool, _ in gateway.calls)


@pytest.mark.asyncio
async def test_arbitrary_engine_error_is_normalized_at_runner_boundary():
    class UnsafeErrorEngine(FakeEngine):
        async def run(self, job, lease_file=None):
            return EngineResult(
                exit_code=0,
                attempted_tool_calls=1,
                successful_tool_calls=0,
                last_error_code="provider secret output",
            )

    gateway = FakeGateway("investigating")
    await Runner(gateway, UnsafeErrorEngine()).run_job(JOB)
    finish = next(args for tool, args in gateway.calls if tool == "tasks_worker_finish")
    assert finish["outcome"] == "failed"
    assert finish["error_code"] == "engine_tools_failed"
    assert "provider secret output" not in str(gateway.calls)


@pytest.mark.asyncio
async def test_gateway_failure_retries_polling_without_work():
    gateway = FakeGateway(failures=1)
    runner = Runner(gateway, FakeEngine(), poll_max_seconds=1)
    task = asyncio.create_task(runner.run_forever())
    await asyncio.sleep(1.05)
    runner.stop()
    await task
    assert [tool for tool, _ in gateway.calls].count("tasks_worker_next") >= 2


@pytest.mark.asyncio
async def test_idle_stop_interrupts_poll_wait_immediately():
    runner = Runner(FakeGateway(), FakeEngine(), poll_max_seconds=300)
    task = asyncio.create_task(runner.run_forever())
    await asyncio.sleep(.05)
    runner.stop()
    await asyncio.wait_for(task, timeout=.2)


@pytest.mark.asyncio
async def test_stop_arriving_during_reconcile_switches_to_release():
    class StopDuringReadGateway(FakeGateway):
        runner = None
        reads = 0

        async def call(self, tool, arguments):
            result = await super().call(tool, arguments)
            if tool == "tasks_get":
                self.reads += 1
                if self.reads == 1:
                    self.runner.stop()
            return result

    gateway = StopDuringReadGateway("investigating")
    runner = Runner(gateway, FakeEngine())
    gateway.runner = runner
    await runner.run_job(JOB)
    assert not any(tool == "tasks_set_status" for tool, _ in gateway.calls)
    assert any(tool == "tasks_release" for tool, _ in gateway.calls)
    finish = next(args for tool, args in gateway.calls if tool == "tasks_worker_finish")
    assert finish["outcome"] == "released"


@pytest.mark.asyncio
async def test_proxy_injects_and_rejects_other_task():
    gateway = FakeGateway()
    proxy = LeasedGatewayProxy(gateway, JOB)
    await proxy.call("approvals_request", {"tool_id": "opnsense_wol_wake"})
    args = gateway.calls[-1][1]
    assert args["task_id"] == JOB.task_id
    assert args["worker_job_id"] == JOB.job_id
    await proxy.call("opnsense_system_status", {})
    infra = gateway.calls[-1][1]
    assert infra["task_id"] == JOB.task_id
    assert infra["worker_job_id"] == JOB.job_id
    assert infra["worker_lease_token"] == JOB.lease_token
    with pytest.raises(GatewayError, match="worker_task_scope_denied"):
        await proxy.call("tasks_add_note", {"task_id": "other", "note": "safe"})
    with pytest.raises(GatewayError, match="worker_task_scope_denied"):
        await proxy.call("tasks_get", {"task_id": "other"})
    with pytest.raises(GatewayError, match="worker_control_denied"):
        await proxy.call("tasks_worker_finish", {})


@pytest.mark.asyncio
async def test_transient_renewal_failure_recovers_before_safety_margin():
    gateway, engine = FakeGateway(failures=1, renew_extension=1), FakeEngine(wait=True)
    short_job = Job("job-1", "task-1", 3, "lease-secret", (datetime.now(UTC) + timedelta(seconds=1)).isoformat(), 1)
    task = asyncio.create_task(Runner(gateway, engine, lease_safety_seconds=.05).run_job(short_job))
    await asyncio.sleep(.9)
    engine.release.set()
    await task
    renewals = [args for tool, args in gateway.calls if tool == "tasks_worker_renew"]
    assert len(renewals) >= 2
    assert renewals[0]["idempotency_key"] == renewals[1]["idempotency_key"]
    assert any(tool == "tasks_worker_finish" for tool, _ in gateway.calls)


@pytest.mark.asyncio
async def test_finish_retries_with_same_idempotency_key():
    class FinishRetryGateway(FakeGateway):
        async def call(self, tool, arguments):
            self.calls.append((tool, arguments))
            if tool == "tasks_get":
                return {"status": "completed", "version": 4, "assigned_agent": "agent:worker:x"}
            if tool == "tasks_worker_finish" and len([name for name, _ in self.calls if name == tool]) == 1:
                raise GatewayError("mcp_unavailable")
            return {"job": None, "retry_after_seconds": 1}

    gateway = FinishRetryGateway()
    await Runner(gateway, FakeEngine()).run_job(JOB)
    finishes = [args for tool, args in gateway.calls if tool == "tasks_worker_finish"]
    assert len(finishes) == 2
    assert finishes[0]["idempotency_key"] == finishes[1]["idempotency_key"]


@pytest.mark.asyncio
async def test_invalid_expiry_never_starts_engine():
    engine = FakeEngine()
    invalid = Job("job-1", "task-1", 3, "lease-secret", "not-a-date", 1)
    with pytest.raises(ValueError):
        await Runner(FakeGateway(), engine).run_job(invalid)
    assert engine.runs == 0


@pytest.mark.asyncio
async def test_gateway_rejects_core_error_envelope(monkeypatch):
    class Content: text = '{"ok":false,"error":{"code":"worker_lease_expired"}}'
    class Result:
        isError = False
        content = [Content()]
    class Session:
        async def call_tool(self, tool, arguments): return Result()
    async def with_session(self, fn):
        return await fn(Session())
    gateway = McpHttpGateway("https://console.example/mcp", "token")
    monkeypatch.setattr(McpHttpGateway, "_with_session", with_session)
    with pytest.raises(GatewayError, match="worker_lease_expired"):
        await gateway.call("tasks_get", {})


@pytest.mark.asyncio
async def test_gateway_preserves_bounded_list_results(monkeypatch):
    class Content: text = '{"ok":true,"result":[{"event":"safe"}]}'
    class Result:
        isError = False
        content = [Content()]
    class Session:
        async def call_tool(self, tool, arguments): return Result()
    async def with_session(self, fn):
        return await fn(Session())
    gateway = McpHttpGateway("https://console.example/mcp", "token")
    monkeypatch.setattr(McpHttpGateway, "_with_session", with_session)
    assert await gateway.call("tasks_events_list", {}) == [{"event": "safe"}]


def test_token_permissions_and_url_policy(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text("test-token\n")
    token.chmod(0o600)
    settings = Settings(mcp_url="https://console.example/mcp", token_file=token, project_dir=tmp_path)
    assert settings.read_token() == "test-token"
    token.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        settings.read_token()
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(mcp_url="http://remote.example/mcp", token_file=token, project_dir=tmp_path)


def test_http_transport_disables_redirects():
    client = McpHttpGateway("https://console.example/mcp", "token")._http_client()
    try:
        assert client.follow_redirects is False
    finally:
        asyncio.run(client.aclose())
