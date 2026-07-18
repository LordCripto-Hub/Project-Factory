#!/bin/bash
set -u
ROOT=${INSTALL_DIR:-$HOME/mypeople}; export PATH="$HOME/.local/bin:$ROOT/bin:/usr/local/bin:/usr/bin:/bin:$PATH" LANG=C.UTF-8 LC_ALL=C.UTF-8
. "$HOME/.config/mypeople/queue.env"
log="$ROOT/run/boss-supervisor.log"
boss_id="$HOST_ID/main:Boss"
nightwatch_id="$HOST_ID/nightwatch:Nightwatch"
pause_file="$ROOT/run/provider-launch.paused"
while :; do
  if [[ "${MYPEOPLE_DISABLE_PROVIDER_LAUNCH:-0}" == "1" || -f "$pause_file" ]]; then
    sleep 1
    continue
  fi
  if [[ -f "$ROOT/run/provider-switch.lock" ]]; then
    sleep 1
    continue
  fi
  if ! tmux has-session -t mc-main:Boss >/dev/null 2>&1; then
    if ! jq -e --arg aid "$boss_id" '.[] | select(.agent_id == $aid)' "$ROOT/run/roster.json" >/dev/null 2>&1; then
      if ! "$ROOT/bin/mp" spawn "$boss_id" --master --backend codex --model gpt-5.6-sol >>"$log" 2>&1; then
        echo "$(date -Is) Boss bootstrap failed" >>"$log"
      fi
    fi
  fi
  if [[ -f "$ROOT/run/nightwatch/CLAUDE.md" ]] && ! tmux has-session -t mc-nightwatch:Nightwatch >/dev/null 2>&1; then
    if ! jq -e --arg aid "$nightwatch_id" '.[] | select(.agent_id == $aid)' "$ROOT/run/roster.json" >/dev/null 2>&1; then
      if ! "$ROOT/bin/mp" spawn "$nightwatch_id" --boss "$boss_id" --cwd "$ROOT/run/nightwatch" --backend codex --model gpt-5.6-luna >>"$log" 2>&1; then
        echo "$(date -Is) Nightwatch bootstrap failed" >>"$log"
      fi
    fi
  fi
  if ! "$ROOT/bin/mp" reconcile >>"$log" 2>&1; then
    echo "$(date -Is) Agent reconcile failed" >>"$log"
  fi
  sleep 15
done
