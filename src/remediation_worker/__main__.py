from __future__ import annotations

import argparse
import asyncio
import signal
from pathlib import Path

from .config import load_settings
from .bridge import serve
from .engines import OpenCodeEngine
from .gateway import McpHttpGateway
from .runner import Runner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "health", "config-check", "bridge"])
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    args = parser.parse_args()
    settings = load_settings(args.config)
    settings.validate_paths()
    if args.command == "bridge":
        asyncio.run(serve(args.config))
        return
    if args.command in {"health", "config-check"}:
        settings.read_token()
        print("configuration valid")
        return
    token = settings.read_token()
    gateway = McpHttpGateway(settings.mcp_url, token)
    engine = OpenCodeEngine(settings.project_dir, "Execute only the assigned remediation task through the fenced MCP bridge.", settings.engine_timeout_seconds, settings.opencode_config)
    runner = Runner(
        gateway,
        engine,
        settings.poll_max_seconds,
        settings.runtime_dir,
        settings.lease_safety_seconds,
        settings.shutdown_grace_seconds,
    )
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, runner.stop)
    loop.run_until_complete(runner.run_forever())


if __name__ == "__main__":
    main()
