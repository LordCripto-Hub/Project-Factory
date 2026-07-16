#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "mypeople-todos": "/home/mp/mypeople/todos",
    "mypeople-run": "/home/mp/mypeople/run",
    "mypeople-status": "/home/mp/mypeople/status",
    "mypeople-config": "/home/mp/.config/mypeople",
    "mypeople-codex": "/home/mp/.codex",
    "mypeople-claude": "/home/mp/.claude",
    "mypeople-recordings": "/home/mp/recordings",
    "mypeople-workspaces": "/home/mp/workspaces",
}

contract = json.loads(
    (ROOT / "docker" / "state-volumes.json").read_text(encoding="utf-8")
)
compose = (ROOT / "docker" / "compose.volume-backed.yml").read_text(encoding="utf-8")
migration = (ROOT / "windows" / "Migrate-MyPeopleDockerState.ps1").read_text(
    encoding="utf-8"
)
upgrade_path = ROOT / "windows" / "Upgrade-MyPeopleDockerImage.ps1"
assert upgrade_path.exists()
upgrade = upgrade_path.read_text(encoding="utf-8")
readme = (ROOT / "README.md").read_text(encoding="utf-8")
manual = (ROOT / "docs" / "USER-MANUAL.md").read_text(encoding="utf-8")

assert contract == EXPECTED
assert "container_name: mypeople" in compose
assert "init: true" in compose
assert "restart: unless-stopped" in compose
assert 'command: ["/home/mp/mypeople/bin/runtime-supervisor.sh"]' in compose
assert "sleep infinity" not in compose
assert "down -v" not in compose
assert "type: bind" in compose
assert "target: /home/mp/mypeople.seed.md" in compose
assert "read_only: true" in compose
assert "tmpfs:" in compose
assert "/run/mypeople-secrets" in compose
assert "uid=1000" in compose
assert "gid=1000" in compose
assert "mode=0700" in compose
assert "MYPEOPLE_MEMORY_TOKEN" not in compose
assert "'bin', 'verify', 'memory-gateway', 'plugins', 'docs', 'docker', 'windows'" in migration
assert "compose.tailscale.yml" in migration
assert "--force-recreate" in upgrade
assert "Invoke-IsolatedVerify.ps1" in upgrade
assert "providerActivationAttempted = $false" in upgrade
assert "docker rename" not in upgrade
assert "MyPeople.ProviderProfiles.psm1" not in upgrade
for public_doc in (readme, manual):
    assert "Upgrade-MyPeopleDockerImage.ps1" in public_doc
    assert "provider sessions" in public_doc.lower()
for volume, target in EXPECTED.items():
    assert f"{volume}:{target}" in compose
    assert f"name: {volume}" in compose

print("PASS volume-backed Docker deployment contract")
