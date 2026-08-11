import asyncio
import json
import os
from pathlib import Path

import pytest

from remediation_worker.bridge import BRIDGE_INSTRUCTIONS, Bridge, read_context, serve
from remediation_worker.gateway import GatewayError
from remediation_worker.protocol import Job


JOB = Job("job", "task", 1, "secret", "", 1)


@pytest.mark.asyncio
async def test_serve_imports_the_pinned_mcp_server_api(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        await serve(tmp_path / "missing.toml")


def test_bridge_instructions_require_canonical_completion():
    assert "tasks_get" in BRIDGE_INSTRUCTIONS[:512]
    assert "tasks_context" in BRIDGE_INSTRUCTIONS[:512]
    assert "tasks_set_status" in BRIDGE_INSTRUCTIONS
    assert "investigating" in BRIDGE_INSTRUCTIONS
    assert "never add task_id" in BRIDGE_INSTRUCTIONS
    assert "tasks_update_summary" in BRIDGE_INSTRUCTIONS
    assert "tasks_complete" in BRIDGE_INSTRUCTIONS


class Tool:
    def __init__(self, name):
        self.name, self.description = name, "test"
        self.inputSchema = {"type": "object", "properties": {"task_id": {"type": "string"}, "worker_job_id": {"type": "string"}, "note": {"type": "string"}}, "required": ["task_id"]}


class Gateway:
    def __init__(self): self.calls = []
    async def list_tools(self): return [Tool("tasks_get"), Tool("tasks_worker_finish"), Tool("tasks_add_note"), Tool("opnsense_system_status"), Tool("future_provider_status")]
    async def call(self, name, args): self.calls.append((name, args)); return {"ok": True}


@pytest.mark.asyncio
async def test_bridge_filters_and_injects_scope():
    gateway = Gateway()
    bridge = Bridge(gateway, JOB)
    tools = await bridge.tools()
    assert [tool.name for tool in tools] == ["tasks_get", "tasks_add_note", "opnsense_system_status"]
    assert "task_id" not in tools[0].inputSchema["properties"]
    await bridge.call("tasks_get", {})
    assert gateway.calls[-1][1] == {"task_id": "task"}
    await bridge.call("tasks_add_note", {"note": "x"})
    assert gateway.calls[-1][1]["worker_job_id"] == "job"
    await bridge.call("opnsense_system_status", {})
    assert gateway.calls[-1][1] == {
        "task_id": "task",
        "worker_job_id": "job",
        "worker_lease_token": "secret",
    }
    with pytest.raises(GatewayError): await bridge.call("tasks_add_note", {"worker_lease_token": "no"})
    with pytest.raises(GatewayError): await bridge.call("tasks_get", {"task_id": "other"})
    with pytest.raises(GatewayError): await bridge.call("tasks_assign", {})
    with pytest.raises(GatewayError): await bridge.call("future_provider_status", {})


def test_context_requires_regular_0600_file(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    context = runtime / "lease"
    context.write_text(json.dumps({"job_id": "j", "task_id": "t", "lease_token": "s"}))
    context.chmod(0o600)
    assert read_context(context, runtime).task_id == "t"
    context.chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        read_context(context, runtime)


@pytest.mark.asyncio
async def test_bridge_only_polls_approvals_requested_by_current_job():
    class ApprovalGateway(Gateway):
        async def list_tools(self):
            return [Tool("approvals_request"), Tool("approvals_get")]

        async def call(self, name, args):
            self.calls.append((name, args))
            if name == "approvals_request":
                return {"id": "approval-current", "task_id": "task", "status": "pending"}
            return {"id": args["approval_id"], "status": "approved"}

    bridge = Bridge(ApprovalGateway(), JOB)
    await bridge.tools()
    with pytest.raises(GatewayError, match="worker_approval_scope_denied"):
        await bridge.call("approvals_get", {"approval_id": "approval-other"})
    await bridge.call("approvals_request", {"tool_id": "opnsense.wol.wake", "input": {}})
    result = await bridge.call("approvals_get", {"approval_id": "approval-current"})
    assert json.loads(result[0].text)["status"] == "approved"
