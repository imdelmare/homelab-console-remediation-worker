# Engine architecture

The remediation worker runs a single AI agent engine at a time, selected by the
`ENGINE` environment variable. The engine launches a vendor-specific binary
(OpenCode, Codex, …) inside a closed, fenced profile. The MCP bridge, lease
lifecycle, task polling and gateway proxy remain identical regardless of the
engine.

## Engine selection

| Variable | Default | Accepted values |
|---|---|---|
| `ENGINE` | `opencode` | `opencode`, `codex` |

Set `ENGINE` in the Compose environment or export it before `docker compose up -d`:

```bash
# Default: OpenCode
docker compose up -d

# Codex (requires implementation)
ENGINE=codex docker compose up -d
```

## Factory discovery

`src/remediation_worker/engines/__init__.py` holds the registry:

```python
_ENGINES = {
    "opencode": OpenCodeEngine,
    # "codex": CodexEngine,  # future
}
```

`create_engine(name, project_dir, timeout_seconds, profile_config, **kwargs)` resolves the name, instantiates the class and returns an `Engine` instance. Unknown names raise `ValueError`. Keyword arguments are forwarded directly — the factory never inspects provider‑specific options.

## Adding an engine

1. Implement the `Engine` protocol from `remediation_worker.protocol`:
   ```python
   class Engine(Protocol):
       async def run(self, job: Job, lease_file: Path | None = None) -> int: ...
       async def terminate(self) -> None: ...
   ```
2. Place the class in `src/remediation_worker/engines/<name>.py`.
3. Register it in `_ENGINES` inside `__init__.py`.
4. Add a closed profile in `profiles/<name>.json`. The profile must:
   - disable every built‑in tool (`"tools": {"*": false}`)
   - define exactly one MCP server (`homelab-remediation`) with the bridge command
   - use the `homelab-remediator` agent with `"permission": {"*": "deny", "homelab-remediation_*": "allow"}`
5. If the engine binary isn't in the base image, add it to the `Dockerfile`.
6. Add focused tests in `tests/test_<name>.py`.
7. Update this document and the conformance matrix.

## Profiles

One JSON file per engine in `profiles/`. The Dockerfile copies the entire
directory into the container's `/etc/homelab-console-remediation-worker/profiles/`.
The `config.toml` field `opencode_config` points to the active profile path
(kept for backward compatibility — always set it to the engine's profile, e.g.
`profiles/opencode.json` or `profiles/codex.json`).

The profile is read‑only (`0444`) and owned by `root`. The engine binary
inherits `OPENCODE_CONFIG` pointing to it. Codex will use an equivalent
mechanism.

## Isolation invariants

Every profile, regardless of engine:

- has zero built‑in tools
- has exactly one MCP server (`homelab-remediation`)
- denies every tool permission except `homelab-remediation_*`
- disables autoupdate, share, snapshot, formatter and LSP
- runs through the same stdio bridge that filters worker‑control tools
- injects the active task and lease through `LeasedGatewayProxy`

The host container already enforces a read‑only rootfs, zero capabilities, zero
ports and zero Docker socket. The profile is an additional defence — the engine
process cannot escape through its own tool configuration even if the container
boundary were somehow breached.
