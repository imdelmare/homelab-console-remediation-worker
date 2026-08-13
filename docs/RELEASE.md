# Container Release

## CI artifact build

GitHub Actions builds and publishes both artifacts only from a semantic-version
Git tag (`vMAJOR.MINOR.PATCH`, with optional SemVer pre-release/build suffix).
The repository is fixed to `ghcr.io/<github.repository>`; manual runs accept no
registry, image, or tag input. The base artifact receives `<semver>` and
`sha-<commit>` tags. The Codex artifact receives `codex-<semver>` and
`codex-sha-<commit>` tags. Tags are discovery labels only: use the digest shown
in the workflow summary for deployment. Each pushed digest has a GitHub build
provenance attestation.

## Deployment and rollback

The fixed deployment directory is `/opt/remediation-worker`. Copy the checked-in
`compose.yaml`, optional `compose.codex.yaml`, `scripts/release-worker`,
`config.toml`, and operator-owned `secrets/` there. Keep `config.toml` and
`secrets/` in place across releases; the release procedure neither writes nor
removes them.

The Codex profile additionally retains operator-owned `codex-home/` and
`codex-config/` directories. Upgrade and rollback recreate only the container;
they do not modify either directory.

CI builds and publishes release artifacts; the deployment host never builds an
image. Obtain the selected artifact's registry digest from the CI workflow.
Only a fully qualified immutable image ending in `@sha256:<64 lowercase hex>`
is accepted. `latest`, tags, and the old implicit local image are rejected.
The artifact must contain the selected engine: the base artifact for OpenCode,
or an artifact built with Codex included for the Codex override.

From `/opt/remediation-worker`, run:

```text
./scripts/release-worker upgrade ghcr.io/<github.repository>@sha256:<digest>
./scripts/release-worker upgrade ghcr.io/<github.repository>@sha256:<digest> --codex
```

The script pulls only that image, runs the fixed `worker` service's
`config-check`, recreates only `worker`, and waits for its Docker health check.
After a healthy release it writes the image and profile to
`.release-state/current` and preserves the former entry in
`.release-state/previous`. That state contains no credentials. If the health
gate fails, it restores the recorded current release automatically; if no
recorded release exists it stops the failed worker instead of leaving it active.

For an explicit rollback, use the recorded previous release:

```text
./scripts/release-worker rollback
```

Rollback also performs the config and health gates. On failure it restores the
pre-rollback current release. Do not edit `.release-state/` manually.

The release script accepts no Compose service, shell command, host, registry
endpoint, or deployment-directory argument. It is intentionally limited to the
local fixed `worker` service.
