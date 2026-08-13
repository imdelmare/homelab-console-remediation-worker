# Homelab Console Remediation Worker

External, lease-fenced worker for `REMEDIATION_WORKER_V1`. It polls a dedicated Homelab Console MCP registration and launches a closed OpenCode or Codex engine profile.

The engine agent receives MCP access only through the mandatory stdio bridge. The fixed profile in `profiles/` starts `python -m remediation_worker bridge --config /etc/homelab-console-remediation-worker/config.toml`; it accepts no task, model, URL or command parameters. The bridge reads the runner-owned 0600 lease-context file, filters worker-control tools and injects the active task and lease through `LeasedGatewayProxy`.

Use `python -m remediation_worker config-check --config config.toml` before installation. Container releases use immutable artifacts through the fixed `/opt/remediation-worker/scripts/release-worker`; see `docs/RELEASE.md`, `docs/INSTALLATION.md`, `docs/ENGINES.md`, `docs/RUNBOOK.md`, and `docs/ROLLBACK.md`.

## Engines

The worker is engine-neutral. Set `engine = "opencode"` (default) or
`engine = "codex"` in `config.toml`. OpenCode uses its read-only JSON profile;
Codex uses fixed native CLI overrides that register only the fenced MCP bridge.
Claude and Cline remain unsupported until equivalent closed profiles pass the
same conformance checks. See [`docs/ENGINES.md`](docs/ENGINES.md).

The recommended evaluation path is the rootless container profile in
`compose.yaml`. It has a read-only root filesystem, drops all Linux
capabilities, exposes no ports, mounts only the dedicated MCP token and the
selected engine's operator-owned authentication, and keeps lease context in an ephemeral `tmpfs`. The
systemd profile remains supported for native installations.
