# Rollback

For a container release rollback, run
`./scripts/release-worker rollback` from `/opt/remediation-worker`. It restores
only the `worker` service from its recorded immutable previous artifact, runs
config validation, and requires health. If that rollback fails, it restores the
pre-rollback current release. It never deletes token, authentication, config,
or data files. See [`RELEASE.md`](RELEASE.md).

To retire the worker:

1. Stop the worker with `docker compose stop worker` (or disable the native
   system service). The bounded shutdown path first attempts a canonical task
   release. Preserve the stopped container until task and lease read-back is
   complete; never delete token or authentication files as part of an automatic
   rollback command.
2. In Homelab Console, disable assignment for this worker client and revoke its `task-worker.v1` capability.
3. Let active leases expire or use the canonical core recovery path to release non-final tasks.
4. Verify no task is assigned to both this worker pull path and `FIXER_DISPATCH_V1`.
5. After read-back confirms no active lease or assigned task, remove the
   container. Pin the last known-good image tag for a worker rollback; do not use
   `latest` for a live drill.
6. To verify rollback, check the console task list and confirm no active leases.
   The worker container logs must show no successful `tasks_worker_next` calls
   after the capability was revoked.

Do not start the legacy and external workers concurrently for the same task boundary.
