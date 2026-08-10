# Homelab Console Remediation Worker

External, lease-fenced worker for `REMEDIATION_WORKER_V1`. It polls only the dedicated Homelab Console MCP registration and launches a closed OpenCode argv profile.

OpenCode receives MCP access only through the mandatory stdio bridge. The fixed OpenCode profile in `docs/opencode.json` starts `python -m remediation_worker bridge --config /etc/homelab-console-remediation-worker/config.toml`; it accepts no task, model, URL or command parameters. The bridge reads the runner-owned 0600 lease-context file, filters worker-control tools and injects the active task and lease through `LeasedGatewayProxy`.

Use `python -m remediation_worker config-check --config config.toml` before installation. See `docs/INSTALLATION.md`, `docs/RUNBOOK.md`, and `docs/ROLLBACK.md`.

The recommended evaluation path is the rootless container profile in
`compose.yaml`. It has a read-only root filesystem, drops all Linux
capabilities, exposes no ports, mounts only the dedicated MCP token and OpenCode
authentication file, and keeps lease context in an ephemeral `tmpfs`. The
systemd profile remains supported for native installations.
