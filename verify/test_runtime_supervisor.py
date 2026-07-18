#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
supervisor = (ROOT / "bin" / "runtime-supervisor.sh").read_text(encoding="utf-8")
launcher = (ROOT / "bin" / "mypeople").read_text(encoding="utf-8")
policy_path = ROOT / "examples" / "routing-policy.example.json"

assert "trap shutdown TERM INT EXIT" in supervisor
assert 'spawn boss-supervisor bash "$ROOT/bin/boss-supervisor.sh"' in supervisor
assert 'spawn workspace-supervisor python3 "$ROOT/bin/workspace-supervisor.py"' in supervisor
assert 'sudo -n install -d -o mp -g mp -m 0750 /home/mp/workspaces' in supervisor
assert 'wait "$pid"' in supervisor
assert 'kill -KILL "$pid"' in supervisor
assert 'printf \'%s\\n\' "$$" >"$ROOT/run/runtime-supervisor.pid"' in supervisor
assert "sudo -n setsid" not in supervisor
assert "runtime-supervisor.pid" in launcher
assert "boss-supervisor.pid" not in launcher
assert policy_path.is_file()
policy = json.loads(policy_path.read_text(encoding="utf-8"))
assert policy["schemaVersion"] == 1
assert policy["tiers"]["economy"]["model"] == "gpt-5.6-luna"
assert policy["tiers"]["standard"]["model"] == "gpt-5.6-terra"
assert policy["tiers"]["strong"]["model"] == "gpt-5.6-sol"
assert policy["projects"]["mypeople"]["maxEscalations"] == 1
assert 'install -d -m 0700 "$ROOT/run/routing-decisions"' in supervisor
assert '[[ -e "$policy_path" ]]' in supervisor
assert 'mktemp "$ROOT/run/.routing-policy.XXXXXX"' in supervisor
assert 'install -m 0600 "$ROOT/examples/routing-policy.example.json"' in supervisor
assert 'mv -n "$policy_tmp" "$policy_path"' in supervisor
assert "printf '%s\\n' +" not in supervisor

print("PASS single foreground runtime supervisor contract")
