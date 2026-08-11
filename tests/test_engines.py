import pytest
import sys

from remediation_worker.config import Settings
from remediation_worker.engines import create_engine, OpenCodeEngine, CodexEngine
from remediation_worker.engines.codex import _CodexDiagnostics
from pathlib import Path


def test_all_engines_registered():
    for name, cls in [("opencode", OpenCodeEngine), ("codex", CodexEngine)]:
        engine = create_engine(name, Path("/tmp"), 1)
        assert isinstance(engine, cls)
        assert callable(engine.run)
        assert callable(engine.terminate)


def test_unknown_engine_rejected():
    with pytest.raises(ValueError, match="unknown engine"):
        create_engine("nonexistent", Path("/tmp"), 1)


def test_each_engine_sets_argv_no_shell():
    for name in ("opencode", "codex"):
        engine = create_engine(name, Path("/tmp"), 1)
        argv = engine.argv()
        assert isinstance(argv, list)
        assert all(isinstance(a, str) for a in argv)
        assert argv[0] in {"opencode", "codex"}
        assert argv[:2] not in (["sh", "-c"], ["bash", "-c"])


def test_config_validates_known_engines(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text("x")
    token.chmod(0o600)
    for engine in ("opencode", "codex"):
        s = Settings(mcp_url="https://example.invalid/mcp", token_file=token, project_dir=tmp_path, engine=engine)
        assert s.engine == engine


def test_config_rejects_unknown_engine(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text("x")
    token.chmod(0o600)
    with pytest.raises(ValueError, match="unknown engine"):
        Settings(mcp_url="https://example.invalid/mcp", token_file=token, project_dir=tmp_path, engine="unknown")


def test_codex_uses_fixed_native_bridge_profile(tmp_path: Path):
    engine = CodexEngine(
        tmp_path,
        1,
        env={"PATH": "/bin", "CODEX_HOME": "/codex", "UNRELATED_SECRET": "no"},
        prompt="fixed prompt",
    )
    argv = engine.argv()
    assert argv[:5] == ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--json"]
    assert "features.shell_tool=false" in argv
    assert 'web_search="disabled"' in argv
    assert f'mcp_servers.homelab-remediation.command="{sys.executable}"' in argv
    assert 'mcp_servers.homelab-remediation.env_vars=["HOMELAB_WORKER_LEASE_FILE"]' in argv
    assert 'mcp_servers.homelab-remediation.default_tools_approval_mode="approve"' in argv
    enabled_tools = next(value for value in argv if value.startswith("mcp_servers.homelab-remediation.enabled_tools="))
    for name in CodexEngine.ENABLED_TOOLS:
        assert f'"{name}"' in enabled_tools
    assert "tasks_worker_next" not in enabled_tools
    assert argv[-1] == "fixed prompt"
    assert engine._env == {"PATH": "/bin", "CODEX_HOME": "/codex"}


def test_codex_default_prompt_requires_canonical_task_workflow(tmp_path: Path):
    prompt = CodexEngine(tmp_path, 1, env={"PATH": "/bin"}).argv()[-1]
    assert "tasks_get" in prompt
    assert "tasks_context" in prompt
    assert "tasks_set_status" in prompt
    assert "investigating" in prompt
    assert "never add task_id" in prompt
    assert "tasks_complete" in prompt
    assert "homelab-remediation" in prompt


def test_codex_diagnostics_count_calls_without_retaining_payloads():
    diagnostics = _CodexDiagnostics()
    diagnostics.consume(b'{"type":"item.started","item":{"id":"one","type":"mcp_tool_call","tool":"tasks_get","arguments":{"secret":"do-not-retain"}}}')
    diagnostics.consume(b'{"type":"item.completed","item":{"id":"one","type":"mcp_tool_call","tool":"tasks_get","status":"completed","result":{"content":[]}}}')
    diagnostics.consume(b'{"type":"item.completed","item":{"id":"two","type":"mcp_tool_call","tool":"tasks_complete","status":"failed","error":"worker_lease_stale: do-not-retain"}}')
    assert diagnostics.attempted == {"one", "two"}
    assert diagnostics.successful == {"one"}
    assert diagnostics.last_error_code == "worker_lease_stale"
    assert "do-not-retain" not in repr(diagnostics)


def test_codex_diagnostics_ignore_unknown_error_text():
    diagnostics = _CodexDiagnostics()
    diagnostics.consume(b'{"type":"item.completed","item":{"id":"one","type":"mcp_tool_call","status":"failed","error":"provider secret output"}}')
    assert diagnostics.last_error_code == "mcp_tool_call_rejected"
    assert "provider secret output" not in repr(diagnostics)
