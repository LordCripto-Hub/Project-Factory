#!/bin/bash
set -euo pipefail
target=""
while (($#)); do case "$1" in -t) shift; target="${1:-}";; esac; shift || true; done
[[ "$target" =~ ^mc-[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$ ]] || { echo "invalid target"; exit 2; }
leader=${target%%:*}; tab=${target#*:}; uniq="_v_${tab}_$$_${RANDOM}"
unset TMUX
exec tmux new-session -t "$leader" -s "$uniq" \; select-window -t "$tab" \; set-option destroy-unattached on
