from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from remediation_worker.protocol import Job


class OpenCodeEngine:
    """Closed OpenCode launch profile. Output is bounded and intentionally discarded."""

    def __init__(self, project_dir: Path, timeout_seconds: int, profile_config: Path | None = None, prompt: str = "", env: dict[str, str] | None = None) -> None:
        info = project_dir.lstat()
        if not project_dir.is_absolute() or not project_dir.is_dir() or info.st_mode & 0o170000 == 0o120000:
            raise ValueError("project_dir must be an existing absolute non-symlink directory")
        self._project_dir, self._prompt, self._timeout = project_dir, prompt or "Execute only the assigned remediation task through the fenced MCP bridge.", timeout_seconds
        self._opencode_config = profile_config
        source = env if env is not None else os.environ
        self._env = {
            key: source[key]
            for key in (
                "HOME",
                "PATH",
                "LANG",
                "LC_ALL",
                "TERM",
                "SSL_CERT_DIR",
                "SSL_CERT_FILE",
                "XDG_CACHE_HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_STATE_HOME",
            )
            if key in source
        }
        self._env.update({
            "OPENCODE_PURE": "true",
            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "true",
        })
        if self._opencode_config is not None:
            self._env["OPENCODE_CONFIG"] = str(self._opencode_config)
        self._process: asyncio.subprocess.Process | None = None

    def argv(self) -> list[str]:
        return ["opencode", "--pure", "run", "--agent", "homelab-remediator", "--format", "json", "--dir", str(self._project_dir), self._prompt]

    async def run(self, job: Job, lease_file: Path | None = None) -> int:
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
        try:
            if getattr(self._process, "stdout", None) is None or getattr(self._process, "stderr", None) is None:
                await asyncio.wait_for(self._process.communicate(), timeout=self._timeout)
            else:
                await asyncio.wait_for(
                    asyncio.gather(self._drain(self._process.stdout), self._drain(self._process.stderr), self._process.wait()),
                    timeout=self._timeout,
                )
        except TimeoutError:
            await self.terminate()
            return 124
        return self._process.returncode or 0

    @staticmethod
    async def _drain(stream: asyncio.StreamReader) -> None:
        # Drain pipes to avoid child deadlock, retaining and logging no model output.
        while await stream.read(65536):
            pass

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
