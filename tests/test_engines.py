import pytest

from remediation_worker.config import Settings
from remediation_worker.engines import create_engine, OpenCodeEngine, CodexEngine, ClaudeEngine, ClineEngine
from remediation_worker.protocol import Engine, Job
from pathlib import Path


JOB = Job("job", "task", 1, "secret", "2099-01-01T00:00:00Z", 1)


def test_all_engines_registered():
    for name, cls in [("opencode", OpenCodeEngine), ("codex", CodexEngine), ("claude", ClaudeEngine), ("cline", ClineEngine)]:
        engine = create_engine(name, Path("/tmp"), 1)
        assert isinstance(engine, cls)
        assert isinstance(engine, Engine)


def test_unknown_engine_rejected():
    with pytest.raises(ValueError, match="unknown engine"):
        create_engine("nonexistent", Path("/tmp"), 1)


def test_each_engine_sets_argv_no_shell():
    for name in ("opencode", "codex", "claude", "cline"):
        engine = create_engine(name, Path("/tmp"), 1)
        argv = engine.argv()
        assert isinstance(argv, list)
        assert all(isinstance(a, str) for a in argv)
        assert "shell" not in str(argv).lower()


def test_config_validates_known_engines(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text("x")
    token.chmod(0o600)
    for engine in ("opencode", "codex", "claude", "cline"):
        s = Settings(mcp_url="https://example.invalid/mcp", token_file=token, project_dir=tmp_path, engine=engine)
        assert s.engine == engine


def test_config_rejects_unknown_engine(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text("x")
    token.chmod(0o600)
    with pytest.raises(ValueError, match="unknown engine"):
        Settings(mcp_url="https://example.invalid/mcp", token_file=token, project_dir=tmp_path, engine="unknown")
