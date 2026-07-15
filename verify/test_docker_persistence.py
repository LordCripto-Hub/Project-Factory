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
}

contract = json.loads(
    (ROOT / "docker" / "state-volumes.json").read_text(encoding="utf-8")
)
compose = (ROOT / "docker" / "compose.volume-backed.yml").read_text(encoding="utf-8")

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
for volume, target in EXPECTED.items():
    assert f"{volume}:{target}" in compose
    assert f"name: {volume}" in compose

print("PASS volume-backed Docker deployment contract")
