import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_container_runs_unprivileged_with_pinned_opencode():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG OPENCODE_VERSION=1.18.8" in dockerfile
    assert 'npm install --global "opencode-ai@${OPENCODE_VERSION}"' in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "ENTRYPOINT [\"/usr/bin/tini\", \"--\"]" in dockerfile
    assert "docker.sock" not in dockerfile


def test_compose_is_read_only_and_exposes_no_ports_or_docker_socket():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "ports:" not in compose
    assert "network_mode: host" not in compose
    assert "docker.sock" not in compose


def test_container_profile_uses_only_the_fenced_bridge():
    profile = json.loads((ROOT / "profiles/opencode.json").read_text(encoding="utf-8"))
    assert profile["tools"] == {"*": False}
    assert list(profile["mcp"]) == ["homelab-remediation"]
def test_codex_profile_exists_and_has_same_structure():
    profile = json.loads((ROOT / "profiles/codex.json").read_text(encoding="utf-8"))
    assert profile["tools"] == {"*": False}
    assert list(profile["mcp"]) == ["homelab-remediation"]
    assert "homelab-remediator" in profile.get("agent", {})
    assert "Codex engine" in profile["agent"]["homelab-remediator"]["description"]

def test_engine_env_default_is_opencode():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "ENGINE: ${ENGINE:-opencode}" in compose

    command = profile["mcp"]["homelab-remediation"]["command"]
    assert command == [
        "/usr/local/bin/python",
        "-m",
        "remediation_worker",
        "bridge",
        "--config",
        "/etc/homelab-console-remediation-worker/config.toml",
    ]
