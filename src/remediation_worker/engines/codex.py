from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from remediation_worker.protocol import EngineResult, Job


_KNOWN_ERROR_CODES = {
    "approval_required",
    "engine_incomplete",
    "invalid_input",
    "mcp_invalid_response",
    "mcp_server_start_failed",
    "mcp_tool_call_rejected",
    "mcp_unavailable",
    "provider_error",
    "provider_timeout",
    "task_version_conflict",
    "unauthorized",
    "worker_approval_scope_denied",
    "worker_capability_required",
    "worker_client_revoked",
    "worker_control_denied",
    "worker_lease_conflict",
    "worker_lease_expired",
    "worker_lease_invalid",
    "worker_lease_stale",
    "worker_protocol_unavailable",
    "worker_task_scope_denied",
}

# Event types Codex emits for MCP tool call lifecycle. v0.147 uses the
# "item." prefix; older or future releases may use different keys.
_CODEX_TOOL_END = frozenset({"item.completed", "tool_call.complete", "tool_call.completed", "item_finished"})


@dataclass
class _CodexDiagnostics:
    attempted: set[str] = field(default_factory=set)
    successful: set[str] = field(default_factory=set)
    last_error_code: str = ""

    def consume(self, raw: bytes) -> None:
        if len(raw) > 1_048_576:
            return
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(event, dict):
            return
        item = event.get("item")
        event_type = event.get("type")
        # Codex 0.147 wraps the tool-call record inside an "item" key with
        # outer event types "item.started"/"item.completed". Later releases
        # or model providers may flatten or rename these fields.
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            return
        call_id = item.get("id")
        if not isinstance(call_id, str) or not call_id:
            return
        self.attempted.add(call_id)
        if not isinstance(event_type, str) or event_type not in _CODEX_TOOL_END:
            return
        error_code = self._error_code(item)
        if error_code:
            self.last_error_code = error_code
        else:
            self.successful.add(call_id)

    @staticmethod
    def _error_code(item: dict[str, Any]) -> str:
        status = item.get("status")
        error = item.get("error")
        # Codex 0.147 may report status values beyond the expected set.
        # Only treat a call as rejected when there is an explicit error field
        # or the status is unambiguously a failure code.
        if error:
            return _find_known_error(error) or "mcp_tool_call_rejected"
        if isinstance(status, str) and status.lower() in {"failed", "error", "rejected", "cancelled", "timeout"}:
            return _find_known_error(item.get("result")) or "mcp_tool_call_rejected"
        # Non-standard status (e.g. Codex-internal values) without an error
        # field is not evidence of failure; treat as unknown but not rejected.
        if status is not None and status not in {"completed", "success"}:
            return _find_known_error(item.get("result")) or "mcp_invalid_response"
        return _find_known_error(item.get("result"))


def _find_known_error(value: Any) -> str:
    """Extract only an allowlisted code; never retain arbitrary engine output."""
    if isinstance(value, dict):
        error = value.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if isinstance(code, str) and code in _KNOWN_ERROR_CODES:
                return code
        for child in value.values():
            found = _find_known_error(child)
            if found:
                return found
        return ""
    if isinstance(value, list):
        for child in value:
            found = _find_known_error(child)
            if found:
                return found
        return ""
    if isinstance(value, str) and len(value) <= 65_536:
        for code in _KNOWN_ERROR_CODES:
            if code in value:
                return code
    return ""


class CodexEngine:
    """Closed Codex launch profile. Output is bounded and intentionally discarded."""

    DEFAULT_PROMPT = (
        "Act as the assigned lease-fenced Homelab Console remediation worker. "
        "Use only tools from the homelab-remediation MCP server; do not merely describe the work. "
        "First call tasks_get with an empty input, then tasks_context, and follow the canonical task goal and stop conditions. "
        "If the task is claimed, call tasks_set_status with status investigating before doing task work. "
        "Keep every infrastructure action read-only unless the task explicitly requires an operator-approved write. "
        "For infrastructure tools, send only the provider inputs shown in their schema; never add task_id, worker_job_id, or worker_lease_token because the bridge injects them. "
        "Before ending, update the task summary with concise evidence and call tasks_complete. "
        "If the goal cannot be completed, record the blocker through task tools instead of claiming success."
    )
    ENABLED_TOOLS = (
        "tasks_get",
        "tasks_context",
        "tasks_set_status",
        "tasks_update_summary",
        "tasks_add_note",
        "tasks_complete",
        "lab_summary",
        "lab_alerts_recent",
        "network_dns_resolve",
        "network_egress_status",
    )

    def __init__(self, project_dir: Path, timeout_seconds: int, profile_config: Path | None = None, prompt: str = "", env: dict[str, str] | None = None) -> None:
        info = project_dir.lstat()
        if not project_dir.is_absolute() or not project_dir.is_dir() or info.st_mode & 0o170000 == 0o120000:
            raise ValueError("project_dir must be an existing absolute non-symlink directory")
        self._project_dir, self._prompt, self._timeout = project_dir, prompt or self.DEFAULT_PROMPT, timeout_seconds
        # Codex receives its closed MCP configuration as fixed CLI overrides.
        # OpenCode JSON profiles are intentionally not passed to this engine.
        del profile_config
        source = env if env is not None else os.environ
        self._env = {
            key: source[key]
            for key in ("HOME", "PATH", "LANG", "LC_ALL", "TERM", "PYTHONPATH", "SSL_CERT_DIR", "SSL_CERT_FILE", "CODEX_HOME", "OPENAI_API_KEY")
            if key in source
        }
        self._process: asyncio.subprocess.Process | None = None

    def argv(self) -> list[str]:
        bridge_args = '["-m","remediation_worker","bridge","--config","/etc/homelab-console-remediation-worker/config.toml"]'
        enabled_tools = "[" + ",".join(f'"{name}"' for name in self.ENABLED_TOOLS) + "]"
        return [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "-c",
            'approval_policy="never"',
            "-c",
            'sandbox_mode="read-only"',
            "-c",
            "features.shell_tool=false",
            "-c",
            "features.apps=false",
            "-c",
            "features.multi_agent=false",
            "-c",
            "features.goals=false",
            "-c",
            "features.memories=false",
            "-c",
            'web_search="disabled"',
            "-c",
            'history.persistence="none"',
            "-c",
            f'mcp_servers.homelab-remediation.command="{sys.executable}"',
            "-c",
            f"mcp_servers.homelab-remediation.args={bridge_args}",
            "-c",
            'mcp_servers.homelab-remediation.env_vars=["HOMELAB_WORKER_LEASE_FILE"]',
            "-c",
            "mcp_servers.homelab-remediation.required=true",
            "-c",
            f"mcp_servers.homelab-remediation.enabled_tools={enabled_tools}",
            "-c",
            # The bridge and Homelab Console core remain the authorization
            # boundary. Codex exec is non-interactive, so its local MCP prompt
            # must not cancel otherwise-valid backend-governed calls.
            'mcp_servers.homelab-remediation.default_tools_approval_mode="approve"',
            self._prompt,
        ]

    async def run(self, job: Job, lease_file: Path | None = None) -> EngineResult:
        del job
        env = dict(self._env)
        if lease_file is not None:
            env["HOMELAB_WORKER_LEASE_FILE"] = str(lease_file)
        self._process = await asyncio.create_subprocess_exec(
            *self.argv(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self._project_dir,
            start_new_session=True,
        )
        diagnostics = _CodexDiagnostics()
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    asyncio.create_task(self._drain_json(self._process.stdout, diagnostics)) if self._process.stdout else asyncio.sleep(0),
                    asyncio.create_task(self._drain(self._process.stderr)) if self._process.stderr else asyncio.sleep(0),
                    self._process.wait(),
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            await self.terminate()
            return EngineResult(
                exit_code=124,
                attempted_tool_calls=len(diagnostics.attempted),
                successful_tool_calls=len(diagnostics.successful),
                last_error_code=diagnostics.last_error_code,
            )
        return EngineResult(
            exit_code=self._process.returncode or 0,
            attempted_tool_calls=len(diagnostics.attempted),
            successful_tool_calls=len(diagnostics.successful),
            last_error_code=diagnostics.last_error_code,
        )

    @staticmethod
    async def _drain(stream: asyncio.StreamReader) -> None:
        while await stream.read(65536):
            pass

    @staticmethod
    async def _drain_json(stream: asyncio.StreamReader, diagnostics: _CodexDiagnostics) -> None:
        buffer = bytearray()
        discarding = False
        while chunk := await stream.read(65536):
            for byte in chunk:
                if byte == 10:
                    if not discarding and buffer:
                        diagnostics.consume(bytes(buffer))
                    buffer.clear()
                    discarding = False
                elif not discarding:
                    if len(buffer) < 1_048_576:
                        buffer.append(byte)
                    else:
                        buffer.clear()
                        discarding = True
        if not discarding and buffer:
            diagnostics.consume(bytes(buffer))

    async def terminate(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        self._signal_group(signal.SIGTERM)
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except TimeoutError:
            self._signal_group(signal.SIGKILL)
            await self._process.wait()

    def _signal_group(self, sig: signal.Signals) -> None:
        if self._process is None:
            return
        pid = getattr(self._process, "pid", None)
        try:
            if isinstance(pid, int):
                os.killpg(pid, sig)
            elif sig == signal.SIGTERM:
                self._process.terminate()
            else:
                self._process.kill()
        except ProcessLookupError:
            pass
