# Conformance matrix

| Core migration | Contract | Adapter | Evidence | Status |
| --- | --- | --- | --- | --- |
| 0021 durable worker jobs | v1 | 0.2.3 | pull, renew, all four finish outcomes, normalized error codes and UUID idempotency tests | covered locally |
| 0022 approval worker binding | v1 | 0.2.3 | `LeasedGatewayProxy` injects task/job/token for approval and task-bound calls | covered in proxy |
| streamable HTTP MCP | v1 | 0.2.3 | official MCP client implementation and task-bound live drill | verified live |
| mandatory OpenCode fenced bridge | v1 | 0.2.3 | explicit 123-tool infrastructure allowlist, deny-new-tool test, schema scrubbing, scope rejection and lease injection tests | covered locally; pending live MCP drill |
| closed engine profile | v1 | 0.2.3 | isolated HOME/XDG, disabled built-ins and exactly one MCP bridge | Codex verified live; OpenCode covered locally |
| rootless container profile | v1 | 0.2.3 | pinned engines, non-root UID, read-only rootfs, dropped capabilities, no ports/socket and ephemeral lease tmpfs | verified live with Codex |
| multi-engine selection | v1 | 0.2.3 | validated TOML selection, `create_engine()` factory, OpenCode JSON profile and fixed Codex-native bridge overrides | Codex verified live; OpenCode live drill pending |
| transient adapter retry | v1 | 0.2.3 | timeout/non-zero engine failures finish as `retry`; core owns backoff and bounded exhaustion | covered locally; live exhaustion drill pending |
| rollback | v1 | 0.2.3 | `docs/ROLLBACK.md` closed sequence, graceful release and no concurrent legacy dispatch | documented; live drill pending |

The contract's core-side grant/revoke, concurrent acquisition, token hashing, and provider approval enforcement are owned and tested by core; this repository does not duplicate them.

Dynamic API-ready tools and future core tools fail closed. Adding one requires an adapter review, allowlist update and release; remote discovery alone never grants model access.

Compatibility tuple: core migrations `0021`/`0022`, contract
`REMEDIATION_WORKER_V1`, adapter `0.2.3`.

The focused core MCP compatibility suite (`test_mcp_clients.py`,
`test_mcp_adapter.py`, `test_remediation_workers.py`) passes against isolated,
ephemeral PostgreSQL databases: 52 tests. The external worker suite passes 48
tests. The Codex live drill completed the canonical lease-fenced workflow and
one task-bound `network.egress.status` invocation. Release completion still
requires the operator-authorized OpenCode live conformance, retry-exhaustion,
revocation and rollback drills; local evidence must not be described as live
conformance.
