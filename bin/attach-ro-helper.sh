#!/bin/bash
set -euo pipefail
target=""
while (($#)); do case "$1" in -t) shift; target="${1:-}";; esac; shift || true; done
[[ "$target" =~ ^mc-[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$ ]] || { echo "invalid target"; exit 2; }
leader=${target%%:*}; tab=${target#*:}; uniq="_ro_${tab}_$$_${RANDOM}"
cleanup(){ tmux kill-session -t "$uniq" 2>/dev/null || true; }
trap cleanup EXIT INT TERM HUP
unset TMUX
tmux new-session -d -t "$leader" -s "$uniq"
tmux select-window -t "$uniq:$tab"
tmux attach -r -f ignore-size -t "$uniq:$tab"
