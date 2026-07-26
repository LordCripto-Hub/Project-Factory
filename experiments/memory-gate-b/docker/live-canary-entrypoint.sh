#!/usr/bin/env bash
set -euo pipefail

readonly token_file="/run/secrets/MYPEOPLE_MEMORY_CANARY_TOKEN"
[[ "${MYPEOPLE_GATE_B_LIVE_CANARY:-}" == "1" ]] || exit 125
[[ "${MYPEOPLE_GATE_B_HOST:-}" == "0.0.0.0" ]] || exit 125
[[ "${MYPEOPLE_GATE_B_PORT:-}" == "18443" ]] || exit 125
[[ -s "$token_file" ]] || exit 125
[[ -d /workspace && -d /project-factory-history-039a62988625 ]] || exit 125
[[ -d /home/mp/mypeople/memory-gateway/node_modules ]] || exit 125

export MYPEOPLE_GATE_B_TOKEN_FILE="$token_file"
export MYPEOPLE_GATE_B_LEDGER=/run/memory-canary-ledger.jsonl
export MYPEOPLE_GATE_B_READY=/run/memory-canary-ready.json
ln -s /home/mp/mypeople/memory-gateway/node_modules /run/node_modules
cp /workspace/docker/taskspec-memory-server.mjs /run/taskspec-memory-server.mjs
exec node /run/taskspec-memory-server.mjs
