# Rollback

1. Disable the worker system service to stop new polling; its bounded shutdown path first attempts a canonical task release.
2. In Homelab Console, disable assignment for this worker client and revoke its `task-worker.v1` capability.
3. Let active leases expire or use the canonical core recovery path to release non-final tasks.
4. Verify no task is assigned to both this worker pull path and `FIXER_DISPATCH_V1`.

Do not start the legacy and external workers concurrently for the same task boundary.
