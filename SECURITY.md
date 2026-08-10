# Security policy

Report vulnerabilities privately to the Homelab Console operator. Do not include bearer tokens, lease tokens, raw model output, or task data in reports.

The worker accepts no task-provided command, endpoint, SSH target, or credentials. Its token file must be owned by the service account and mode `0600`. Revoke the dedicated MCP client capability if compromise is suspected.

The container runs as UID/GID `10001`, exposes no ports, uses a read-only root
filesystem, drops every Linux capability and never mounts the Docker socket.
Only the dedicated MCP token and OpenCode authentication file are mounted
read-only. Lease context is written to an ephemeral `tmpfs` and removed when the
engine exits. Containerization is isolation in depth and does not replace MCP
identity, lease fencing or per-invocation write approval.
