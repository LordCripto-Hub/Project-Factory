#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
supervisor = (ROOT / "bin" / "runtime-supervisor.sh").read_text(encoding="utf-8")
launcher = (ROOT / "bin" / "mypeople").read_text(encoding="utf-8")

assert "trap shutdown TERM INT EXIT" in supervisor
assert 'spawn boss-supervisor bash "$ROOT/bin/boss-supervisor.sh"' in supervisor
assert 'spawn workspace-supervisor python3 "$ROOT/bin/workspace-supervisor.py"' in supervisor
assert 'wait "$pid"' in supervisor
assert 'kill -KILL "$pid"' in supervisor
assert 'printf \'%s\\n\' "$$" >"$ROOT/run/runtime-supervisor.pid"' in supervisor
assert "sudo -n setsid" not in supervisor
assert "runtime-supervisor.pid" in launcher
assert "boss-supervisor.pid" not in launcher

print("PASS single foreground runtime supervisor contract")
