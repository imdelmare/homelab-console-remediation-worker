from __future__ import annotations

from pathlib import Path
from typing import Any

from remediation_worker.protocol import Engine

from .opencode import OpenCodeEngine
from .codex import CodexEngine


__all__ = ["OpenCodeEngine", "CodexEngine", "create_engine"]


_ENGINES: dict[str, type[Any]] = {
    "opencode": OpenCodeEngine,
    "codex": CodexEngine,
}


def create_engine(
    engine: str,
    project_dir: Path,
    timeout_seconds: int,
    profile_config: Path | None = None,
    **kwargs: Any,
) -> Engine:
    """Resolve a named engine and return a configured instance.

    Supported engines: opencode and codex.
    Unknown names raise :class:`ValueError`. Keyword arguments are forwarded
    to the concrete engine constructor — the factory never inspects them.
    """
    cls = _ENGINES.get(engine)
    if cls is None:
        raise ValueError(f"unknown engine: {engine!r}")
    return cls(project_dir, timeout_seconds, profile_config, **kwargs)
