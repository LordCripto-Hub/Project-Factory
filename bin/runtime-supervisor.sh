#!/bin/bash
set -u

ROOT=${INSTALL_DIR:-$HOME/mypeople}
export INSTALL_DIR="$ROOT"
export PATH="$HOME/.local/bin:$ROOT/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

. "$HOME/.config/mypeople/queue.env"
mkdir -p "$ROOT/run"
if [[ "${MYPEOPLE_TAILSCALE_ENABLED:-0}" == "1" ]]; then
  mkdir -p "$ROOT/run/tailscale-state"
fi
sudo -n install -d -o mp -g mp -m 0750 /home/mp/workspaces
printf '%s\n' "$$" >"$ROOT/run/runtime-supervisor.pid"

declare -A children=()
stopping=0

alive() {
  local pid=${children[$1]:-} stat=""
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  stat=$(ps -o stat= -p "$pid" 2>/dev/null)
  [[ "$stat" != Z* ]]
}

spawn() {
  local name=$1 pid=""
  shift
  alive "$name" && return 0
  pid=${children[$name]:-}
  [[ -z "$pid" ]] || wait "$pid" 2>/dev/null || true
  "$@" </dev/null >>"$ROOT/run/$name.log" 2>&1 &
  pid=$!
  children[$name]=$pid
  printf '%s\n' "$pid" >"$ROOT/run/$name.pid"
}

shutdown() {
  (( stopping )) && return 0
  stopping=1
  trap - TERM INT EXIT
  local pid deadline=$((SECONDS + 20)) any
  for pid in "${children[@]}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  while (( SECONDS < deadline )); do
    any=0
    for pid in "${children[@]}"; do
      kill -0 "$pid" 2>/dev/null && any=1
    done
    (( any )) || break
    sleep 1
  done
  for pid in "${children[@]}"; do
    kill -KILL "$pid" 2>/dev/null || true
  done
  for pid in "${children[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
  if [[ $(cat "$ROOT/run/runtime-supervisor.pid" 2>/dev/null) == "$$" ]]; then
    rm -f "$ROOT/run/runtime-supervisor.pid"
  fi
}
trap shutdown TERM INT EXIT

while (( ! stopping )); do
  spawn queue-server python3 "$ROOT/bin/queue-server.py"
  spawn todo-server env PATH="$HOME/.local/bin:$ROOT/bin:$PATH" python3 "$ROOT/bin/todo-server.py"
  spawn queue-client python3 "$ROOT/bin/queue-client.py"
  spawn board-export python3 "$ROOT/bin/board-export.py"
  spawn workspace-supervisor python3 "$ROOT/bin/workspace-supervisor.py"
  spawn ttyd-write ttyd -i 0.0.0.0 -W -a -p "$TTYD_PORT" -t disableLeaveAlert=true "$ROOT/bin/attach-helper.sh"
  spawn ttyd-read ttyd -i 0.0.0.0 -a -p "$TTYD_RO_PORT" -t disableLeaveAlert=true "$ROOT/bin/attach-ro-helper.sh"
  spawn boss-supervisor bash "$ROOT/bin/boss-supervisor.sh"
  if [[ "${MYPEOPLE_TAILSCALE_ENABLED:-0}" == "1" ]]; then
    if ! sudo -n tailscale --socket="$ROOT/run/tailscale-state/tailscaled.sock" status >/dev/null 2>&1; then
      spawn tailscaled sudo -n /usr/sbin/tailscaled \
        --state="$ROOT/run/tailscale-state/tailscaled.state" \
        --socket="$ROOT/run/tailscale-state/tailscaled.sock" \
        --tun=tailscale0
    fi
    if [[ -S "$ROOT/run/tailscale-state/tailscaled.sock" ]]; then
      sudo -n ln -sf "$ROOT/run/tailscale-state/tailscaled.sock" /var/run/tailscale/tailscaled.sock || true
    fi
  fi
  sleep 2 &
  pid=$!
  wait "$pid" || true
done
