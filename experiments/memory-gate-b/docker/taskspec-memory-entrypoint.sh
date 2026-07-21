#!/usr/bin/env bash
set -euo pipefail

readonly FINAL_DATASET_NAME="project-factory-history-80dce6f86632"
server_pid=""

fail() {
  printf 'taskspec memory isolation failure: %s\n' "$1" >&2
  exit 125
}

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

[[ "${MYPEOPLE_TASKSPEC_ISOLATED:-}" == "1" ]] || fail "missing isolation marker"
[[ "$(id -u)" != "0" ]] || fail "container must run as a non-root user"
[[ "${MYPEOPLE_TASKSPEC_DATASET_NAME:-}" == "$FINAL_DATASET_NAME" ]] || fail "unexpected dataset name"
[[ "${MYPEOPLE_MEMORY_ALLOW_HTTP:-0}" == "0" ]] || fail "HTTP memory override is forbidden"
[[ -d /workspace && -d /project-factory-history-80dce6f86632 && -d /evidence ]] || fail "required mounts are missing"
[[ -f /home/mp/mypeople/bin/project_context.py ]] || fail "image compiler missing"
[[ -f /home/mp/mypeople/memory-gateway/memory-gateway.mjs ]] || fail "image gateway missing"
[[ -d /home/mp/mypeople/memory-gateway/node_modules ]] || fail "image gateway dependencies missing"

for secret_name in OPENAI_API_KEY ANTHROPIC_API_KEY CODEX_API_KEY GH_TOKEN GITHUB_TOKEN
do
  [[ -z "$(printenv "$secret_name" 2>/dev/null || true)" ]] || fail "provider credential environment must be empty"
done

if touch /workspace/.taskspec-memory-write-probe 2>/dev/null; then
  rm -f /workspace/.taskspec-memory-write-probe
  fail "source mount is writable"
fi
if touch /project-factory-history-80dce6f86632/.taskspec-memory-write-probe 2>/dev/null; then
  rm -f /project-factory-history-80dce6f86632/.taskspec-memory-write-probe
  fail "dataset mount is writable"
fi
touch /evidence/.taskspec-memory-write-probe || fail "evidence mount is not writable"
rm -f /evidence/.taskspec-memory-write-probe

mkdir -p /work/tls
chmod 700 /work/tls
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /work/tls/server-key.pem \
  -out /work/tls/server-cert.pem \
  -days 1 \
  -subj "/CN=127.0.0.1" \
  -addext "subjectAltName=IP:127.0.0.1" \
  >/dev/null 2>&1
chmod 600 /work/tls/server-key.pem /work/tls/server-cert.pem

ln -s /home/mp/mypeople/memory-gateway/node_modules /work/node_modules
cp /workspace/docker/taskspec-memory-server.mjs /work/taskspec-memory-server.mjs
export MYPEOPLE_MEMORY_TOKEN
MYPEOPLE_MEMORY_TOKEN="$(openssl rand -hex 24)"
export NODE_EXTRA_CA_CERTS=/work/tls/server-cert.pem
export MYPEOPLE_GATE_B_TLS_KEY=/work/tls/server-key.pem
export MYPEOPLE_GATE_B_TLS_CERT=/work/tls/server-cert.pem
export MYPEOPLE_GATE_B_LEDGER=/work/request-ledger.jsonl
export MYPEOPLE_GATE_B_READY=/work/server-ready.json

node /work/taskspec-memory-server.mjs >/work/server.stdout 2>/work/server.stderr &
server_pid="$!"
for _ in $(seq 1 100); do
  [[ -s "$MYPEOPLE_GATE_B_READY" ]] && break
  kill -0 "$server_pid" 2>/dev/null || fail "MCP fixture exited before ready"
  sleep 0.05
done
[[ -s "$MYPEOPLE_GATE_B_READY" ]] || fail "MCP fixture readiness timeout"

PYTHONPATH=/workspace/src python3 /workspace/scripts/run_taskspec_memory_gate.py \
  --dataset /project-factory-history-80dce6f86632 \
  --lock /workspace/docker/history-hybrid.dataset-lock.json \
  --project-context /home/mp/mypeople/bin/project_context.py \
  --server-ready "$MYPEOPLE_GATE_B_READY" \
  --ledger "$MYPEOPLE_GATE_B_LEDGER" \
  --output-dir /evidence

python3 - /evidence <<'PY'
from pathlib import Path
import os
import sys

token = os.environ["MYPEOPLE_MEMORY_TOKEN"]
root = Path(sys.argv[1])
for path in root.iterdir():
    if path.is_file() and token in path.read_text(encoding="utf-8"):
        raise SystemExit("synthetic bearer leaked into evidence")
for forbidden in ("server-key.pem", "server-cert.pem", "request-ledger.jsonl"):
    if (root / forbidden).exists():
        raise SystemExit(f"ephemeral runtime artifact leaked: {forbidden}")
PY
