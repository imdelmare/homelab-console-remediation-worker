# Security policy

Report vulnerabilities privately to the Homelab Console operator. Do not include bearer tokens, lease tokens, raw model output, or task data in reports.

The worker accepts no task-provided command, endpoint, SSH target, or credentials. Its token file must be owned by the service account and mode `0600`. Revoke the dedicated MCP client capability if compromise is suspected.
