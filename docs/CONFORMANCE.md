# Conformance matrix

| Core migration | Contract | Adapter | Evidence | Status |
| --- | --- | --- | --- | --- |
| 0021 durable worker jobs | v1 | 0.2.0 | pull, renew, finish, UUID idempotency tests | covered |
| 0022 approval worker binding | v1 | 0.2.0 | `LeasedGatewayProxy` injects task/job/token for approval and task-bound calls | covered in proxy |
| streamable HTTP MCP | v1 | 0.2.0 | official MCP client implementation and task-bound live drill | verified live |
| mandatory OpenCode fenced bridge | v1 | 0.2.0 | explicit 123-tool infrastructure allowlist, deny-new-tool test, schema scrubbing, scope rejection and lease injection tests | covered locally; pending live MCP drill |
| closed engine profile | v1 | 0.2.0 | isolated HOME/XDG, disabled built-ins and exactly one MCP bridge | Codex verified live; OpenCode covered locally |
| rootless container profile | v1 | 0.2.0 | pinned engines, non-root UID, read-only rootfs, dropped capabilities, no ports/socket and ephemeral lease tmpfs | verified live with Codex |
| multi-engine selection | v1 | 0.2.0 | validated TOML selection, `create_engine()` factory, OpenCode JSON profile and fixed Codex-native bridge overrides | Codex verified live; OpenCode live drill pending |

The contract's core-side grant/revoke, concurrent acquisition, token hashing, and provider approval enforcement are owned and tested by core; this repository does not duplicate them.

Dynamic API-ready tools and future core tools fail closed. Adding one requires an adapter review, allowlist update and release; remote discovery alone never grants model access.

The focused core MCP compatibility suite (`test_mcp_clients.py`,
`test_mcp_adapter.py`, `test_remediation_workers.py`) passes against isolated,
ephemeral PostgreSQL databases: 52 tests. The external worker suite passes 41
tests. The Codex live drill completed the canonical lease-fenced workflow and
one task-bound `network.egress.status` invocation; OpenCode live conformance
remains pending.
