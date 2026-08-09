"""The only MCP server exposed to the remediation model."""
from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Any

from .config import load_settings
from .gateway import GatewayError, LeasedGatewayProxy, McpHttpGateway
from .protocol import Job
from .allowed_tools import INFRASTRUCTURE_TOOLS

_READ = {"tasks_get", "tasks_context", "tasks_events_list", "tasks_findings_list", "tasks_checks_list"}
_TASK_ALLOWED = _READ | {
    "tasks_set_status",
    "tasks_update_summary",
    "tasks_release",
    "tasks_add_note",
    "tasks_add_finding",
    "tasks_resolve_finding",
    "tasks_add_check",
    "tasks_complete_check",
    "tasks_skip_check",
    "tasks_complete",
}
_APPROVAL_ALLOWED = {"approvals_request", "approvals_get"}
_CONTROL = {"task_id", "worker_job_id", "worker_lease_token"}


def _allowed_tool(name: str) -> bool:
    if name.startswith("tasks_"):
        return name in _TASK_ALLOWED
    if name.startswith("approvals_"):
        return name in _APPROVAL_ALLOWED
    return name in INFRASTRUCTURE_TOOLS


def read_context(path: Path, runtime_dir: Path) -> Job:
    if path.parent.resolve() != runtime_dir.resolve():
        raise ValueError("lease context outside runtime directory")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as context_file:
            info = os.fstat(context_file.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()
            ):
                raise ValueError("invalid lease context permissions")
            raw = context_file.read(4097)
        if len(raw) > 4096:
            raise ValueError
        data = json.loads(raw)
        if set(data) != {"job_id", "task_id", "lease_token"} or not all(isinstance(data[key], str) and data[key] for key in data):
            raise ValueError
    except OSError as exc:
        raise ValueError("invalid lease context permissions") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        if str(exc) == "invalid lease context permissions":
            raise
        raise ValueError("invalid lease context") from exc
    return Job(data["job_id"], data["task_id"], 0, data["lease_token"], "", 0)


def _schema(schema: dict[str, Any]) -> dict[str, Any]:
    result = dict(schema)
    properties = dict(result.get("properties", {}))
    for key in _CONTROL:
        properties.pop(key, None)
    result["properties"] = properties
    result["required"] = [key for key in result.get("required", []) if key not in _CONTROL]
    return result


class Bridge:
    def __init__(self, gateway: McpHttpGateway, job: Job) -> None:
        self.gateway, self.proxy, self.job = gateway, LeasedGatewayProxy(gateway, job), job
        self._allowed: set[str] | None = None
        self._approval_ids: set[str] = set()

    async def tools(self) -> list[Any]:
        from mcp.types import Tool
        tools = []
        allowed: set[str] = set()
        for tool in await self.gateway.list_tools():
            if not _allowed_tool(tool.name):
                continue
            tools.append(Tool(name=tool.name, description=tool.description, inputSchema=_schema(tool.inputSchema)))
            allowed.add(tool.name)
        self._allowed = allowed
        return tools

    async def call(self, name: str, arguments: dict[str, Any] | None) -> list[Any]:
        from mcp.types import TextContent
        payload = dict(arguments or {})
        if self._allowed is None:
            await self.tools()
        if name not in self._allowed or any(key in payload for key in ("worker_job_id", "worker_lease_token")):
            raise GatewayError("worker_control_denied")
        if payload.get("task_id") not in (None, self.job.task_id):
            raise GatewayError("worker_task_scope_denied")
        if name == "approvals_get" and payload.get("approval_id") not in self._approval_ids:
            raise GatewayError("worker_approval_scope_denied")
        if name in _READ:
            payload["task_id"] = self.job.task_id
        result = await self.proxy.call(name, payload)
        if name == "approvals_request":
            approval_id = result.get("id") if isinstance(result, dict) else None
            if isinstance(approval_id, str) and approval_id:
                self._approval_ids.add(approval_id)
        text = json.dumps(result, separators=(",", ":"))
        if len(text) > 65536:
            raise GatewayError("mcp_response_too_large")
        return [TextContent(type="text", text=text)]


async def serve(config_path: Path) -> None:
    from mcp.server.lowlevel import Server
    from mcp.server.models import InitializationOptions, NotificationOptions
    from mcp.server.stdio import stdio_server
    settings = load_settings(config_path)
    settings.validate_paths()
    context = os.environ.get("HOMELAB_WORKER_LEASE_FILE")
    if not context:
        raise ValueError("missing lease context")
    bridge = Bridge(McpHttpGateway(settings.mcp_url, settings.read_token()), read_context(Path(context), settings.runtime_dir))
    server = Server("homelab-remediation-bridge")

    @server.list_tools()
    async def list_tools():
        return await bridge.tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None):
        return await bridge.call(name, arguments)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, InitializationOptions(server_name="homelab-remediation-bridge", server_version="1", capabilities=server.get_capabilities(notification_options=NotificationOptions(), experimental_capabilities={})))
