# Engine architecture

The remediation worker runs a single AI agent engine at a time, selected by the
validated `engine` field in `config.toml`. The engine launches a vendor-specific binary
(OpenCode, Codex, …) inside a closed, fenced profile. The MCP bridge, lease
lifecycle, task polling and gateway proxy remain identical regardless of the
engine.

## Engine selection

| Setting | Default | Accepted values |
|---|---|---|
| `engine` | `opencode` | `opencode`, `codex` |

Set the value in `config.toml` before `docker compose up -d`:

```bash
engine = "codex"
```

## Factory selection

`src/remediation_worker/engines/__init__.py` resolves the closed set explicitly:

```python
if engine == "opencode":
    return OpenCodeEngine(project_dir, timeout_seconds, profile_config)
if engine == "codex":
    return CodexEngine(project_dir, timeout_seconds, profile_config)
```

`create_engine(name, project_dir, timeout_seconds, profile_config)` returns an
`Engine` instance. Unknown names raise `ValueError`. Callers cannot override the
fixed prompt, argument vector or child environment.

## Adding an engine

1. Implement the `Engine` protocol from `remediation_worker.protocol`:
   ```python
   class Engine(Protocol):
       async def run(self, job: Job, lease_file: Path | None = None) -> EngineResult: ...
       async def terminate(self) -> None: ...
   ```
2. Place the class in `src/remediation_worker/engines/<name>.py`.
3. Add an explicit closed branch to `create_engine()` inside `__init__.py`.
4. Add a vendor-native closed profile. It must disable built-in action tools and
   define exactly one MCP server (`homelab-remediation`) with the fixed bridge
   command. Never pass a profile from one engine to another.
5. If the engine binary isn't in the base image, add it to the `Dockerfile`.
6. Add focused tests in `tests/test_<name>.py`.
7. Update this document and the conformance matrix.

## Profiles

OpenCode loads the root-owned, read-only `profiles/opencode.json` through
`OPENCODE_CONFIG`. Codex does not consume that JSON file: `CodexEngine` supplies
fixed native `-c` overrides for read-only sandboxing, disabled shell/web search,
and the sole `homelab-remediation` stdio server. The active lease filename is
the only forwarded variable. Codex authentication remains in the operator-owned
`CODEX_HOME`; it is never copied into a profile or logged.

## Isolation invariants

Every engine profile:

- disables built-in action tools supported by that engine
- has exactly one MCP server (`homelab-remediation`)
- denies every tool permission except `homelab-remediation_*`
- disables optional network/search and update behavior where supported
- runs through the same stdio bridge that filters worker‑control tools
- injects the active task and lease through `LeasedGatewayProxy`

The host container already enforces a read‑only rootfs, zero capabilities, zero
ports and zero Docker socket. The profile is an additional defence — the engine
process cannot escape through its own tool configuration even if the container
boundary were somehow breached.
