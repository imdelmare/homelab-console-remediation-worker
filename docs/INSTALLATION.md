# Installation

## Container installation (recommended for evaluation)

The container includes the worker package and pinned OpenCode `1.18.8`. Codex
`0.147.0` is included only when built with `INCLUDE_CODEX=true`. It runs
as UID/GID `10001`, has no published ports, uses a read-only root filesystem,
drops all capabilities and does not mount a Docker socket.

1. Copy `config.container.example.toml` to `config.toml` and set only the fixed
   Homelab Console MCP HTTPS endpoint.
2. Create `secrets/mcp-token` containing the dedicated MCP bearer token. For
   OpenCode, also create `secrets/opencode-auth.json` from the provider-owned
   authentication file. For Codex, use an operator-owned `CODEX_HOME` mount as
   described below. Never commit authentication material.
3. On a Linux host, set mounted credential files to owner `10001:10001` and
   mode `0600`. The worker deliberately rejects a token file with broader
   permissions or a different owner.
4. Build and validate without starting the poll loop:

   ```text
   docker compose build --pull
   docker compose run --rm worker config-check --config /etc/homelab-console-remediation-worker/config.toml
   docker compose run --rm --entrypoint opencode worker --version
   ```

5. See [`docs/ENGINES.md`](ENGINES.md) for engine architecture, selection and how to add a new engine.
   For Codex, build with `INCLUDE_CODEX=true`, set `engine = "codex"`, and mount
   the operator-owned OAuth directory at the `CODEX_HOME` path. Do not copy or
   commit its `auth.json`.
6. Before granting `task-worker.v1`, inspect the selected engine's resolved
   configuration in an isolated one-off container. Confirm that built-ins are
   disabled and the only MCP server is `homelab-remediation`.
7. Start with `docker compose up -d`, then inspect container health. Do not
   assign a live task until the operator has completed the capability grant and
   drill plan.

The Compose service has no inbound listener. It needs outbound HTTPS access to
the declared MCP endpoint and the selected model provider. Runtime, cache,
config and state paths are ephemeral; authentication remains operator-owned and
lease files exist only in `tmpfs` while a job runs.

## Native systemd installation

1. Create a dedicated, non-login service user and install this package in a Python 3.12 virtual environment.
2. Register a dedicated MCP client in Homelab Console and have an operator grant `task-worker.v1`; never reuse an interactive or another engine's token.
3. Copy `config.example.toml` to a protected location and create the token file mode `0600`.
4. Run `python -m remediation_worker config-check --config /etc/homelab-console-remediation-worker/config.toml`.
5. For OpenCode, copy `profiles/opencode.json` to the configured path. Codex
   uses fixed native CLI overrides and does not consume the OpenCode profile.
   Do not add other MCP servers or allow user/project config to override the
   closed engine configuration.
6. Create `/var/lib/homelab-console-remediation-worker/runtime` owned by the service account with mode `0700`; it holds per-job 0600 context files only while an engine runs.
7. Verify the resolved engine configuration before enabling the unit: all built-in tools and every MCP prefix except `homelab-remediation_*` must remain disabled. OpenCode configuration is merged, so this check is mandatory even with the closed profile and project-config suppression.
8. Install the unit example and enable it after conformance tests pass.

The MCP URL defaults to HTTPS. Plain HTTP is rejected except for loopback development endpoints. Redirects are not followed by the worker transport profile.
