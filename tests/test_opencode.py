import asyncio
from pathlib import Path

import pytest

from remediation_worker.engines.opencode import OpenCodeEngine
from remediation_worker.protocol import Job


JOB = Job("job", "task", 1, "secret", "2099-01-01T00:00:00Z", 1)


@pytest.mark.asyncio
async def test_exact_argv_filtered_env_and_no_shell(monkeypatch, tmp_path: Path):
    observed = {}

    class Process:
        returncode = 0
        async def communicate(self): return (b"model secret", b"stderr secret")

    async def create(*argv, **kwargs):
        observed["argv"], observed["kwargs"] = argv, kwargs
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    engine = OpenCodeEngine(tmp_path, "fixed prompt", 1, env={"PATH": "/bin", "SECRET": "no"})
    assert await engine.run(JOB) == 0
    assert observed["argv"] == ("opencode", "--pure", "run", "--agent", "homelab-remediator", "--format", "json", "--dir", str(tmp_path), "fixed prompt")
    assert observed["kwargs"]["env"] == {
        "PATH": "/bin",
        "OPENCODE_PURE": "true",
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "true",
    }
    assert observed["kwargs"]["cwd"] == tmp_path
    assert observed["kwargs"]["start_new_session"] is True
    assert "shell" not in observed["kwargs"]


def test_config_is_fixed_environment_not_caller_argv(tmp_path: Path):
    config = tmp_path / "opencode.json"
    config.write_text("{}")
    engine = OpenCodeEngine(tmp_path, "fixed prompt", 1, opencode_config=config, env={"PATH": "/bin"})
    assert "--config" not in engine.argv()
    assert engine._env["OPENCODE_CONFIG"] == str(config)


@pytest.mark.asyncio
async def test_timeout_terminates_then_returns_bounded_error(monkeypatch, tmp_path: Path):
    class Process:
        returncode = None
        terminated = False
        async def communicate(self): await asyncio.Event().wait()
        def terminate(self): self.terminated = True; self.returncode = -15
        async def wait(self): return self.returncode

    process = Process()
    async def create(*argv, **kwargs): return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    assert await OpenCodeEngine(tmp_path, "fixed", 0.01).run(JOB) == 124
    assert process.terminated
