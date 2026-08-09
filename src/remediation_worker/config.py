from __future__ import annotations

import os
import stat
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    mcp_url: str
    token_file: Path
    project_dir: Path
    runtime_dir: Path = Path("/var/lib/homelab-console-remediation-worker/runtime")
    opencode_config: Path = Path("/etc/homelab-console-remediation-worker/opencode.json")
    poll_max_seconds: int = Field(default=30, ge=1, le=300)
    engine_timeout_seconds: int = Field(default=900, ge=1, le=3600)
    shutdown_grace_seconds: int = Field(default=15, ge=1, le=120)
    lease_safety_seconds: int = Field(default=5, ge=1, le=30)

    @field_validator("mcp_url")
    @classmethod
    def safe_mcp_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("mcp_url cannot contain credentials, query or fragment")
        if parsed.scheme == "https" and parsed.hostname:
            return value
        if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
            return value
        raise ValueError("mcp_url must use HTTPS; HTTP is allowed only for loopback")

    def read_token(self) -> str:
        info = self.token_file.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("token_file must be a regular file mode 0600")
        token = self.token_file.read_text(encoding="utf-8").strip()
        if not token or len(token) > 4096 or "\n" in token or "\r" in token:
            raise ValueError("token_file is empty")
        return token

    @field_validator("project_dir", "runtime_dir", "opencode_config")
    @classmethod
    def absolute_paths(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("paths must be absolute")
        return value

    def validate_paths(self) -> None:
        info = self.project_dir.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("project_dir must be an existing non-symlink directory")
        self.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.runtime_dir.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("runtime_dir must be a non-symlink directory mode 0700")
        info = self.opencode_config.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("opencode_config must be a non-writable regular file")


def load_settings(path: Path) -> Settings:
    import tomllib

    with path.open("rb") as config_file:
        return Settings.model_validate(tomllib.load(config_file))
