#!/bin/bash
set -u
ROOT=${INSTALL_DIR:-$HOME/mypeople}; export INSTALL_DIR="$ROOT" PATH="$HOME/.local/bin:$ROOT/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8
. "$HOME/.config/mypeople/queue.env"
mkdir -p "$ROOT/run"
alive(){ local f="$ROOT/run/$1.pid" p="" st=""; [[ -f "$f" ]] && p=$(cat "$f" 2>/dev/null); [[ -n "$p" ]] || return 1; kill -0 "$p" 2>/dev/null || return 1; st=$(ps -o stat= -p "$p" 2>/dev/null); [[ "$st" != Z* ]]; }
spawn(){ local name=$1; shift; alive "$name" && return; setsid "$@" </dev/null >>"$ROOT/run/$name.log" 2>&1 & echo $! >"$ROOT/run/$name.pid"; }
while :; do
  spawn queue-server python3 "$ROOT/bin/queue-server.py"
  spawn todo-server env PATH="$HOME/.local/bin:$ROOT/bin:$PATH" python3 "$ROOT/bin/todo-server.py"
  spawn queue-client python3 "$ROOT/bin/queue-client.py"
  spawn board-export python3 "$ROOT/bin/board-export.py"
  spawn ttyd-write ttyd -i 0.0.0.0 -W -a -p "$TTYD_PORT" -t disableLeaveAlert=true "$ROOT/bin/attach-helper.sh"
  spawn ttyd-read ttyd -i 0.0.0.0 -a -p "$TTYD_RO_PORT" -t disableLeaveAlert=true "$ROOT/bin/attach-ro-helper.sh"
  if ! sudo -n tailscale --socket="$ROOT/run/tailscale-state/tailscaled.sock" status >/dev/null 2>&1; then
    sudo -n setsid /usr/sbin/tailscaled --state="$ROOT/run/tailscale-state/tailscaled.state" --socket="$ROOT/run/tailscale-state/tailscaled.sock" --tun=tailscale0 >>"$ROOT/run/tailscale-state/tailscaled.log" 2>&1 </dev/null &
    sleep 1; sudo -n ln -sf "$ROOT/run/tailscale-state/tailscaled.sock" /var/run/tailscale/tailscaled.sock || true
  fi
  sleep 2
done
