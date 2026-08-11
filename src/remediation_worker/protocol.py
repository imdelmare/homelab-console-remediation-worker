from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol


Outcome = Literal["completed", "released", "retry", "failed"]


@dataclass(frozen=True)
class Job:
    job_id: str
    task_id: str
    task_version: int
    lease_token: str
    lease_expires_at: str
    attempt: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("invalid worker job")
        string_fields = ("job_id", "task_id", "lease_token", "lease_expires_at")
        if any(not isinstance(data[key], str) or not data[key] for key in string_fields):
            raise ValueError("invalid worker job")
        if not isinstance(data["task_version"], int) or data["task_version"] < 1:
            raise ValueError("invalid worker job")
        if not isinstance(data["attempt"], int) or data["attempt"] < 1:
            raise ValueError("invalid worker job")
        return cls(**{key: data[key] for key in cls.__dataclass_fields__})


@dataclass(frozen=True)
class EngineResult:
    """Bounded engine metadata. It must never contain model or tool payloads."""

    exit_code: int
    attempted_tool_calls: int = 0
    successful_tool_calls: int = 0
    last_error_code: str = ""


class Gateway(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any]) -> Any: ...


class Engine(Protocol):
    async def run(self, job: Job, lease_file: Path | None = None) -> EngineResult: ...
    async def terminate(self) -> None: ...
