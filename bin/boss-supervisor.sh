#!/bin/bash
set -u
ROOT=${INSTALL_DIR:-$HOME/mypeople}; export PATH="$HOME/.local/bin:$ROOT/bin:/usr/local/bin:/usr/bin:/bin:$PATH" LANG=C.UTF-8 LC_ALL=C.UTF-8
. "$HOME/.config/mypeople/queue.env"
log="$ROOT/run/boss-supervisor.log"
boss_id="$HOST_ID/main:Boss"
nightwatch_id="$HOST_ID/nightwatch:Nightwatch"
while :; do
  if ! tmux has-session -t mc-main:Boss >/dev/null 2>&1; then
    if jq -e --arg aid "$boss_id" '.[] | select(.agent_id == $aid)' "$ROOT/run/roster.json" >/dev/null 2>&1; then
      if ! "$ROOT/bin/mp" revive "$boss_id" >>"$log" 2>&1; then
        echo "$(date -Is) Boss revive failed" >>"$log"
      fi
    else
      if ! "$ROOT/bin/mp" spawn "$boss_id" --master --backend codex --model gpt-5.6-sol >>"$log" 2>&1; then
        echo "$(date -Is) Boss bootstrap failed" >>"$log"
      fi
    fi
  fi
  if [[ -f "$ROOT/run/nightwatch/CLAUDE.md" ]] && ! tmux has-session -t mc-nightwatch:Nightwatch >/dev/null 2>&1; then
    if jq -e --arg aid "$nightwatch_id" '.[] | select(.agent_id == $aid)' "$ROOT/run/roster.json" >/dev/null 2>&1; then
      if ! "$ROOT/bin/mp" revive "$nightwatch_id" >>"$log" 2>&1; then
        echo "$(date -Is) Nightwatch revive failed" >>"$log"
      fi
    else
      if ! "$ROOT/bin/mp" spawn "$nightwatch_id" --boss "$boss_id" --cwd "$ROOT/run/nightwatch" --backend codex --model gpt-5.6-luna >>"$log" 2>&1; then
        echo "$(date -Is) Nightwatch bootstrap failed" >>"$log"
      fi
    fi
  fi
  sleep 5
done
