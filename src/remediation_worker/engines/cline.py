from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from remediation_worker.protocol import Job


class ClineEngine:
    """Closed Cline launch profile. Output is bounded and discarded."""

    def __init__(self, project_dir: Path, timeout_seconds: int, profile_config: Path | None = None, prompt: str = "", env: dict[str, str] | None = None) -> None:
        info = project_dir.lstat()
        if not project_dir.is_absolute() or not project_dir.is_dir() or info.st_mode & 0o170000 == 0o120000:
            raise ValueError("project_dir must be an existing absolute non-symlink directory")
        self._project_dir, self._prompt, self._timeout = project_dir, prompt or "Execute only the assigned remediation task through the fenced MCP bridge.", timeout_seconds
        self._profile_config = profile_config
        source = env if env is not None else os.environ
        self._env = {
            key: source[key]
            for key in ("HOME", "PATH", "LANG", "LC_ALL", "TERM", "SSL_CERT_DIR", "SSL_CERT_FILE")
            if key in source
        }
        # Cline uses provider API keys via environment
        self._process: asyncio.subprocess.Process | None = None

    def argv(self) -> list[str]:
        return ["cline", self._prompt, "--dangerously-skip-permissions"]

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
            await asyncio.wait_for(
                asyncio.gather(
                    asyncio.create_task(self._drain(self._process.stdout)) if self._process.stdout else asyncio.sleep(0),
                    asyncio.create_task(self._drain(self._process.stderr)) if self._process.stderr else asyncio.sleep(0),
                    self._process.wait(),
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            await self.terminate()
            return 124
        return self._process.returncode or 0

    @staticmethod
    async def _drain(stream: asyncio.StreamReader) -> None:
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
