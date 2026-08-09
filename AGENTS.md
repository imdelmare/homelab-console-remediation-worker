# Worker invariants

- Never accept or execute a generic shell command, command template, SSH target, or HTTP target from a task or model.
- Never mount or access a Docker socket.
- Homelab Console MCP is the sole path to core task and infrastructure actions.
- Never store, print, or log secrets, bearer tokens, lease tokens, or raw engine/MCP output.
- The runner owns the active task, job, and lease. Models cannot select or override them.
- Do not bypass `LeasedGatewayProxy` for live task-bound mutations. The OpenCode stdio bridge is an explicit release gate.
