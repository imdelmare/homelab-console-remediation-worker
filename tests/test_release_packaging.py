from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_is_valid_yaml():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    assert set(workflow["jobs"]) == {"test", "base", "codex"}
    assert workflow["jobs"]["base"]["needs"] == "test"
    assert workflow["jobs"]["codex"]["needs"] == "test"


def test_compose_requires_a_release_artifact_and_never_builds_locally():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "image: ${WORKER_IMAGE:?set an immutable worker artifact image}" in compose
    assert "build:" not in compose


def test_release_script_is_fixed_to_worker_and_uses_immutable_health_gated_releases():
    script = (ROOT / "scripts/release-worker").read_text(encoding="utf-8")
    assert "DEPLOY_DIR=/opt/remediation-worker" in script
    assert "@sha256:[0-9a-f]{64}$" in script
    assert "latest is not a release artifact" in script
    assert 'run --rm --no-deps worker config-check' in script
    assert 'up -d --no-deps --force-recreate worker' in script
    assert "health_gate" in script
    assert "restore_or_stop" in script
    assert "stop worker || true" in script
    assert "usage: $0 upgrade IMAGE@sha256:DIGEST [--codex] | rollback" in script


def test_release_documentation_covers_base_codex_and_stateful_rollback():
    release = (ROOT / "docs/RELEASE.md").read_text(encoding="utf-8")
    assert "/opt/remediation-worker" in release
    assert "--codex" in release
    assert ".release-state/previous" in release
    assert "config-check" in release
    assert "health" in release


def test_ci_builds_and_attests_fixed_ghcr_base_and_codex_artifacts():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "IMAGE_NAME: ghcr.io/${{ github.repository }}" in workflow
    assert "workflow_dispatch:" in workflow
    assert "inputs:" not in workflow
    assert 'tags:\n      - "v*"' in workflow
    assert "Require a semantic-version tag" in workflow
    assert "type=ref,event=tag" in workflow
    assert "type=sha,format=short,prefix=sha-" in workflow
    assert "type=ref,event=tag,prefix=codex-" in workflow
    assert "type=sha,format=short,prefix=codex-sha-" in workflow
    assert "build-args: INCLUDE_CODEX=true" in workflow
    assert workflow.count("actions/attest-build-provenance@v2") == 2
    assert workflow.count("subject-digest: ${{ steps.build.outputs.digest }}") == 2


def test_codex_compose_override_mounts_only_the_codex_identity():
    codex_compose = (ROOT / "compose.codex.yaml").read_text(encoding="utf-8")
    assert "volumes: !override" in codex_compose
    assert "./secrets/codex-home:" in codex_compose
    assert "CODEX_HOME:" in codex_compose
    assert "opencode-auth.json" not in codex_compose
