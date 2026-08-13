from __future__ import annotations

from pathlib import Path
from remediation_worker.protocol import Engine

from .opencode import OpenCodeEngine
from .codex import CodexEngine


__all__ = ["OpenCodeEngine", "CodexEngine", "create_engine"]


def create_engine(
    engine: str,
    project_dir: Path,
    timeout_seconds: int,
    profile_config: Path | None = None,
) -> Engine:
    """Resolve a named engine and return a configured instance.

    Supported engines: opencode and codex.
    Unknown names raise :class:`ValueError`. Production configuration cannot
    override the fixed engine prompt, argument vector or child environment.
    """
    if engine == "opencode":
        return OpenCodeEngine(project_dir, timeout_seconds, profile_config)
    if engine == "codex":
        return CodexEngine(project_dir, timeout_seconds, profile_config)
    raise ValueError(f"unknown engine: {engine!r}")
