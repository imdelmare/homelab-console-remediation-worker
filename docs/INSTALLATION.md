# Installation

1. Create a dedicated, non-login service user and install this package in a Python 3.12 virtual environment.
2. Register a dedicated MCP client in Homelab Console and have an operator grant `task-worker.v1`; never reuse an interactive or another engine's token.
3. Copy `config.example.toml` to a protected location and create the token file mode `0600`.
4. Run `python -m remediation_worker config-check --config /etc/homelab-console-remediation-worker/config.toml`.
5. Install `docs/opencode.json` as `/etc/homelab-console-remediation-worker/opencode.json`. Do not add other MCP servers or allow a user/project OpenCode config to override this closed profile.
6. Create `/var/lib/homelab-console-remediation-worker/runtime` owned by the service account with mode `0700`; it holds per-job 0600 context files only while an engine runs.
7. Verify the resolved OpenCode configuration before enabling the unit: all built-in tools and every MCP prefix except `homelab-remediation_*` must remain disabled. OpenCode configuration is merged, so this check is mandatory even with the closed profile and project-config suppression.
8. Install the unit example and enable it after conformance tests pass.

The MCP URL defaults to HTTPS. Plain HTTP is rejected except for loopback development endpoints. Redirects are not followed by the worker transport profile.
