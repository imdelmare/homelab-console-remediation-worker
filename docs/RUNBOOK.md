# Runbook

Run one process: `python -m remediation_worker run --config /etc/homelab-console-remediation-worker/config.toml`.

The runner acquires at most one job, renews while OpenCode runs, retries transient renewal failures only inside the lease safety window, and terminates the engine before local authorization becomes unsafe. It reconciles canonical `tasks_get` state after exit. Only canonical `completed` or unassigned `open` states produce successful finish outcomes. Any remaining claimed/investigating task is moved to `blocked` with a normalized engine error, then finished failed. An engine exit code alone never means remediation succeeded.

Do not inspect or enable raw subprocess output. On a stop signal, the process terminates the complete engine process group and makes a bounded canonical `tasks.release` plus `tasks.worker.finish(released)` attempt. Lease expiry remains the recovery authority if that attempt cannot complete safely.
