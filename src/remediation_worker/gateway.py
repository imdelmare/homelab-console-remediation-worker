from __future__ import annotations

import json
from typing import Any

import httpx

from .protocol import Gateway, Job


class GatewayError(RuntimeError):
    pass


class McpHttpGateway:
    """Official MCP streamable-HTTP client with bounded, structured responses."""

    def __init__(self, url: str, token: str, timeout_seconds: int = 30) -> None:
        self.url, self._token, self._timeout = url, token, timeout_seconds

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers={"Authorization": f"Bearer {self._token}"}, timeout=httpx.Timeout(self._timeout), follow_redirects=False, verify=True)

    async def _session(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        client = self._http_client()
        try:
            async with streamable_http_client(self.url, http_client=client, terminate_on_close=True) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        finally:
            await client.aclose()

    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        try:
            async for session in self._session():
                result = await session.call_tool(tool, arguments)
        except Exception as exc:
            raise GatewayError("mcp_unavailable") from exc
        if result.isError or len(result.content) != 1 or not hasattr(result.content[0], "text"):
            raise GatewayError("mcp_invalid_response")
        try:
            text = result.content[0].text
            if not isinstance(text, str) or len(text) > 65536:
                raise ValueError("response too large")
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GatewayError("mcp_invalid_response") from exc
        if not isinstance(payload, dict):
            raise GatewayError("mcp_invalid_response")
        if payload.get("ok") is False:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise GatewayError(code if isinstance(code, str) and len(code) <= 64 else "mcp_error")
        value = payload.get("result", payload)
        return value

    async def list_tools(self) -> list[Any]:
        try:
            async for session in self._session():
                tools = list((await session.list_tools()).tools)
                if len(tools) > 512:
                    raise GatewayError("mcp_invalid_response")
                return tools
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("mcp_unavailable") from exc
        raise GatewayError("mcp_invalid_response")


class LeasedGatewayProxy:
    """Inject runner-owned lease metadata; never let an adapter choose its scope."""

    _TASK_READS = {"tasks_get", "tasks_context", "tasks_events_list", "tasks_findings_list", "tasks_checks_list"}
    _UNSCOPED_READS = {"approvals_get"}
    _WORKER = {"tasks_worker_next", "tasks_worker_renew", "tasks_worker_finish"}

    def __init__(self, gateway: Gateway, job: Job) -> None:
        self._gateway, self._job = gateway, job

    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        payload = dict(arguments)
        if "worker_job_id" in payload or "worker_lease_token" in payload:
            raise GatewayError("worker_control_denied")
        if tool in self._WORKER:
            raise GatewayError("worker_control_denied")
        if payload.get("task_id") is not None and payload["task_id"] != self._job.task_id:
            raise GatewayError("worker_task_scope_denied")
        if tool in self._TASK_READS:
            payload["task_id"] = self._job.task_id
        elif tool not in self._UNSCOPED_READS:
            # Every task mutation, approval request and infrastructure call is
            # lease-bound. The bridge only exposes tools listed by the core, so
            # an unclassified tool is treated as infrastructure, never as an
            # unscoped escape hatch.
            payload["task_id"] = self._job.task_id
            payload["worker_job_id"] = self._job.job_id
            payload["worker_lease_token"] = self._job.lease_token
        return await self._gateway.call(tool, payload)
