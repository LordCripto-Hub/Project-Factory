#!/bin/bash
set -uo pipefail

if [[ ${MP_VERIFY_ISOLATED:-} != 1 ]]; then
  echo "Refusing to initialize verifier runtime without the isolated container marker." >&2
  exit 125
fi

SOURCE=/workspace
ROOT=/tmp/mypeople
VERIFY_HOME=/tmp/verify-home
CONFIG=$VERIFY_HOME/.config/mypeople/queue.env
EVIDENCE=${MP_VERIFY_EVIDENCE_DIR:-/evidence}
RUNTIME_PID=""
RESULT=1

capture_evidence() {
  mkdir -p "$EVIDENCE/runtime"
  if [[ -d "$ROOT/run" ]]; then
    find "$ROOT/run" -maxdepth 3 -type f \( -name '*.log' -o -name '*.json' \) -exec cp --parents '{}' "$EVIDENCE/runtime" \; 2>/dev/null || true
  fi
  if [[ -d "$ROOT/status" ]]; then
    cp -a "$ROOT/status" "$EVIDENCE/runtime/status" 2>/dev/null || true
  fi
}

cleanup() {
  local deadline
  if [[ -n "$RUNTIME_PID" ]] && kill -0 "$RUNTIME_PID" 2>/dev/null; then
    kill -TERM "$RUNTIME_PID" 2>/dev/null || true
    deadline=$((SECONDS + 15))
    while kill -0 "$RUNTIME_PID" 2>/dev/null && (( SECONDS < deadline )); do sleep 1; done
    kill -KILL "$RUNTIME_PID" 2>/dev/null || true
    wait "$RUNTIME_PID" 2>/dev/null || true
  fi
  tmux kill-server 2>/dev/null || true
  if (( RESULT != 0 )); then capture_evidence; fi
}
trap cleanup EXIT INT TERM

mkdir -p "$ROOT" "$EVIDENCE" "$VERIFY_HOME"
if ! command -v tar >/dev/null 2>&1; then
  echo "The isolated verifier image must provide tar." >&2
  exit 125
fi
if ! tar -C "$SOURCE" \
  --exclude=.git \
  --exclude=.env \
  --exclude=.env.* \
  --exclude=.codex \
  --exclude=.claude \
  --exclude=run \
  --exclude=status \
  --exclude=todos \
  --exclude=recordings \
  --exclude=verify/node_modules \
  --exclude=verify/screenshots \
  --exclude=verify/videos \
  --exclude=memory-gateway/node_modules \
  -cf - . | tar -C "$ROOT" -xf -; then
  echo "Unable to copy the sanitized verifier source tree." >&2
  exit 125
fi
for relative in verify/node_modules memory-gateway/node_modules; do
  packaged="/home/mp/mypeople/$relative"
  target="$ROOT/$relative"
  if [[ ! -e "$target" && -d "$packaged" ]]; then
    ln -s "$packaged" "$target"
  fi
done

mkdir -p "$(dirname "$CONFIG")" "$ROOT/run/boss" "$ROOT/run/eng" "$ROOT/run/nightwatch" \
  "$ROOT/run/project-profiles" "$ROOT/run/taskspecs" "$ROOT/status" "$ROOT/todos" \
  "$ROOT/verify/videos" "$ROOT/verify/screenshots" /tmp/verify-bin
printf '[]\n' >"$ROOT/run/roster.json"
printf '[]\n' >"$ROOT/run/agents.json"
cp "$ROOT/plans/nightwatch-claude.md" "$ROOT/run/nightwatch/CLAUDE.md"

cat >"$CONFIG" <<'EOF'
QUEUE_SECRET=synthetic-verify-secret
NIGHTWATCH_TOKEN=synthetic-nightwatch-token
HOST_ID=node-1
BOSS_AGENT=node-1/main:Boss
NIGHTWATCH_AGENT=node-1/nightwatch:Nightwatch
BIND_ADDR=127.0.0.1
HUD_PORT=9900
TODO_PORT=9933
TTYD_PORT=7681
TTYD_RO_PORT=7682
TTYD_PUBLIC_URL=http://100.64.0.1:7681
QUEUE_URL=http://127.0.0.1:9900
TODO_URL=http://127.0.0.1:9933
BOARD_PATH=/tmp/mypeople/todos/board.v2.json
ROSTER_PATH=/tmp/mypeople/run/roster.json
AGENTS_PATH=/tmp/mypeople/run/agents.json
STATUS_DIR=/tmp/mypeople/status
EXPORT_REPO=/tmp/mypeople/export
PROJECT_PROFILES_DIR=/tmp/mypeople/run/project-profiles
TASKSPECS_DIR=/tmp/mypeople/run/taskspecs
EOF

cat >/tmp/verify-bin/codex <<'EOF'
#!/bin/bash
printf 'OpenAI Codex\nHow can I help?\n'
exec sleep infinity
EOF
cat >/tmp/verify-bin/claude <<'EOF'
#!/bin/bash
printf 'Claude Code\nHow can I help?\n'
exec sleep infinity
EOF
cat >/tmp/verify-bin/tailscale <<'EOF'
#!/bin/bash
case " $* " in
  *' ip -4 '*) printf '100.64.0.1\n' ;;
  *' status '*) printf '{"Self":{"TailscaleIPs":["100.64.0.1"]}}\n' ;;
  *) exit 1 ;;
esac
EOF
chmod 0700 /tmp/verify-bin/codex /tmp/verify-bin/claude /tmp/verify-bin/tailscale

CLEAN_PATH="/tmp/verify-bin:$ROOT/bin:/home/mp/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CLEAN_ENV=(
  "HOME=$VERIFY_HOME" "USER=mp" "LOGNAME=mp" "LANG=C.UTF-8" "LC_ALL=C.UTF-8"
  "PATH=$CLEAN_PATH" "INSTALL_DIR=$ROOT" "PYTHONPATH=$ROOT/bin"
  "MYPEOPLE_CONFIG_PATH=$CONFIG" "MP_VERIFY_ISOLATED=1" "MP_VERIFY_EVIDENCE_DIR=$EVIDENCE"
  "MP_VERIFY_TOOL_BIN=/tmp/verify-bin"
  "QUEUE_SECRET=synthetic-verify-secret" "NIGHTWATCH_TOKEN=synthetic-nightwatch-token"
  "HOST_ID=node-1" "BOSS_AGENT=node-1/main:Boss"
  "NIGHTWATCH_AGENT=node-1/nightwatch:Nightwatch" "BIND_ADDR=127.0.0.1"
  "HUD_PORT=9900" "TODO_PORT=9933" "TTYD_PORT=7681" "TTYD_RO_PORT=7682"
  "TTYD_PUBLIC_URL=http://100.64.0.1:7681" "QUEUE_URL=http://127.0.0.1:9900"
  "TODO_URL=http://127.0.0.1:9933" "BOARD_PATH=$ROOT/todos/board.v2.json"
  "ROSTER_PATH=$ROOT/run/roster.json" "AGENTS_PATH=$ROOT/run/agents.json"
  "STATUS_DIR=$ROOT/status" "EXPORT_REPO=$ROOT/export"
  "PROJECT_PROFILES_DIR=$ROOT/run/project-profiles" "TASKSPECS_DIR=$ROOT/run/taskspecs"
  "PLAYWRIGHT_BROWSERS_PATH=/home/mp/.cache/ms-playwright"
  "MYPEOPLE_DISABLE_PROVIDER_LAUNCH=1"
  "ANTHROPIC_API_KEY=" "OPENAI_API_KEY=" "CODEX_API_KEY=" "GH_TOKEN="
  "GITHUB_TOKEN=" "TAILSCALE_AUTHKEY=" "MYPEOPLE_MEMORY_TOKEN="
)

mkdir -p "$ROOT/status/mc-main" "$ROOT/status/mc-nightwatch"
cat >"$ROOT/run/roster.json" <<'EOF'
[
  {
    "agent_id": "node-1/main:Boss",
    "host": "node-1",
    "session": "main",
    "tab": "Boss",
    "backend": "codex",
    "state": "alive",
    "is_master": true,
    "retired": false,
    "spawn_cmd": "mp spawn node-1/main:Boss --backend codex --master",
    "summary": "autonomous plan approve queue mp verify fire-and-forget"
  },
  {
    "agent_id": "node-1/nightwatch:Nightwatch",
    "host": "node-1",
    "session": "nightwatch",
    "tab": "Nightwatch",
    "backend": "codex",
    "state": "alive",
    "is_master": false,
    "retired": false,
    "spawn_cmd": "mp spawn node-1/nightwatch:Nightwatch --backend codex",
    "summary": "nightwatch ceo-equivalent approve whatsapp never-done"
  }
]
EOF
cat >"$ROOT/status/mc-main/Boss.json" <<'EOF'
{"state":"alive","status":"idle","summary":"autonomous plan approve queue mp verify fire-and-forget","backend":"codex"}
EOF
cat >"$ROOT/status/mc-nightwatch/Nightwatch.json" <<'EOF'
{"state":"alive","status":"idle","summary":"nightwatch ceo-equivalent approve whatsapp never-done","backend":"codex"}
EOF
env -i "${CLEAN_ENV[@]}" tmux new-session -d -s mc-main -n Boss /tmp/verify-bin/codex
env -i "${CLEAN_ENV[@]}" tmux new-session -d -s mc-nightwatch -n Nightwatch /tmp/verify-bin/codex

env -i "${CLEAN_ENV[@]}" bash "$ROOT/bin/runtime-supervisor.sh" &
RUNTIME_PID=$!

ready=0
for _ in $(seq 1 90); do
  if env -i "${CLEAN_ENV[@]}" curl -fsS http://127.0.0.1:9900/health >/dev/null 2>&1 \
    && env -i "${CLEAN_ENV[@]}" curl -fsS http://127.0.0.1:9933/health >/dev/null 2>&1; then
    agents=$(env -i "${CLEAN_ENV[@]}" curl -fsS -H 'X-Queue-Secret: synthetic-verify-secret' http://127.0.0.1:9900/agents 2>/dev/null || printf '[]')
    if printf '%s' "$agents" | jq -e 'map(.agent_id) | index("node-1/main:Boss") and index("node-1/nightwatch:Nightwatch")' >/dev/null 2>&1; then
      ready=1
      break
    fi
  fi
  sleep 1
done
if (( ! ready )); then
  echo "Disposable MyPeople runtime did not become ready." >&2
  RESULT=1
  exit "$RESULT"
fi

case "${MP_VERIFY_MODE:-}" in
  full)
    env -i "${CLEAN_ENV[@]}" bash "$ROOT/verify/run-suite.sh"
    ;;
  smoke)
    if [[ -z ${MP_VERIFY_SMOKE_COMMAND:-} ]]; then
      echo "Smoke verification mode requires an explicit command from the host launcher." >&2
      RESULT=125
      exit "$RESULT"
    fi
    env -i "${CLEAN_ENV[@]}" bash -lc "$MP_VERIFY_SMOKE_COMMAND"
    ;;
  *)
    echo "Unknown isolated verifier mode; use a host launcher." >&2
    RESULT=125
    exit "$RESULT"
    ;;
esac
RESULT=$?
exit "$RESULT"
