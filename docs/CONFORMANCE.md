# Conformance matrix

| Core migration | Contract | Adapter | Evidence | Status |
| --- | --- | --- | --- | --- |
| 0021 durable worker jobs | v1 | 0.1.0 | pull, renew, finish, UUID idempotency tests | covered |
| 0022 approval worker binding | v1 | 0.1.0 | `LeasedGatewayProxy` injects task/job/token for approval and task-bound calls | covered in proxy |
| streamable HTTP MCP | v1 | 0.1.0 | official MCP client implementation, no live test | pending integration |
| mandatory OpenCode fenced bridge | v1 | 0.1.0 | explicit 123-tool infrastructure allowlist, deny-new-tool test, schema scrubbing, scope rejection and lease injection tests | covered locally; pending live MCP drill |
| closed OpenCode profile | v1 | 0.1.0 | `opencode 1.18.8 debug config` with isolated HOME/XDG confirms built-ins disabled and exactly one MCP bridge | verified locally |

The contract's core-side grant/revoke, concurrent acquisition, token hashing, and provider approval enforcement are owned and tested by core; this repository does not duplicate them.

Dynamic API-ready tools and future core tools fail closed. Adding one requires an adapter review, allowlist update and release; remote discovery alone never grants model access.

The focused core compatibility suites (`test_remediation_workers.py`, `test_mcp_adapter.py`, `test_execution.py`) pass against an isolated ephemeral PostgreSQL cluster: 50 tests. The adapter fake-only suite passes 24 tests. Live bearer-token, assignment and infrastructure execution remain an operator-controlled deployment drill, not local conformance evidence.
