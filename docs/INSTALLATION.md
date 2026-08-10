# Installation

## Container installation (recommended for evaluation)

The container includes the worker package and pinned OpenCode `1.18.8`. It runs
as UID/GID `10001`, has no published ports, uses a read-only root filesystem,
drops all capabilities and does not mount a Docker socket.

1. Copy `config.container.example.toml` to `config.toml` and set only the fixed
   Homelab Console MCP HTTPS endpoint.
2. Create `secrets/mcp-token` containing the dedicated MCP bearer token and
   `secrets/opencode-auth.json` containing the OpenCode provider authentication
   exported from `~/.local/share/opencode/auth.json`. Never commit either file.
3. On a Linux host, set both files to owner `10001:10001` and mode `0600`. The
   worker deliberately rejects a token file with broader permissions or a
   different owner.
4. Build and validate without starting the poll loop:

   ```text
   docker compose build --pull
   docker compose run --rm worker config-check --config /etc/homelab-console-remediation-worker/config.toml
   docker compose run --rm --entrypoint opencode worker --version
   ```

5. Profiles live in `profiles/`: one JSON file per engine. The `ENGINE` env var
   selects which profile is loaded. `opencode` is the default. Switch engines
   by setting `ENGINE=codex` in the Compose environment.
6. Before granting `task-worker.v1`, inspect the resolved OpenCode profile in an
   isolated one-off container and confirm that built-ins are disabled and the
   only MCP server is `homelab-remediation`.
7. Start with `docker compose up -d`, then inspect container health. Do not
   assign a live task until the operator has completed the capability grant and
   drill plan.

The Compose service has no inbound listener. It needs outbound HTTPS access to
the declared MCP endpoint and the selected OpenCode model provider. Runtime,
cache, config and state paths are ephemeral; the OpenCode authentication file is
mounted read-only and lease files exist only in `tmpfs` while a job runs.

## Native systemd installation

1. Create a dedicated, non-login service user and install this package in a Python 3.12 virtual environment.
2. Register a dedicated MCP client in Homelab Console and have an operator grant `task-worker.v1`; never reuse an interactive or another engine's token.
3. Copy `config.example.toml` to a protected location and create the token file mode `0600`.
4. Run `python -m remediation_worker config-check --config /etc/homelab-console-remediation-worker/config.toml`.
5. Install `docs/opencode.json` as `/etc/homelab-console-remediation-worker/opencode.json`. Do not add other MCP servers or allow a user/project OpenCode config to override this closed profile.
6. Create `/var/lib/homelab-console-remediation-worker/runtime` owned by the service account with mode `0700`; it holds per-job 0600 context files only while an engine runs.
7. Verify the resolved OpenCode configuration before enabling the unit: all built-in tools and every MCP prefix except `homelab-remediation_*` must remain disabled. OpenCode configuration is merged, so this check is mandatory even with the closed profile and project-config suppression.
8. Install the unit example and enable it after conformance tests pass.

The MCP URL defaults to HTTPS. Plain HTTP is rejected except for loopback development endpoints. Redirects are not followed by the worker transport profile.
