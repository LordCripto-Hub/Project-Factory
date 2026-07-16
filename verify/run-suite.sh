#!/bin/bash
set -euo pipefail

if [[ ${MP_VERIFY_ISOLATED:-} != 1 ]]; then
  echo "Refusing to run the full verifier outside an isolated disposable container." >&2
  exit 125
fi

ROOT=${INSTALL_DIR:?INSTALL_DIR is required}
VERIFY="$ROOT/verify"
export INSTALL_DIR="$ROOT" PYTHONPATH="$ROOT/bin"
TOOL_BIN=${MP_VERIFY_TOOL_BIN:-}
export PATH="${TOOL_BIN:+$TOOL_BIN:}$HOME/.local/bin:$ROOT/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

need=()
for command in curl jq git tmux node npm ss ffmpeg python3; do
  command -v "$command" >/dev/null 2>&1 || need+=("$command")
done
if ((${#need[@]})); then
  printf 'Missing verifier dependencies in the selected image: %s\n' "${need[*]}" >&2
  exit 1
fi
if [[ ! -d "$VERIFY/node_modules/playwright" ]]; then
  echo "Playwright is absent from the selected image; the isolated verifier never downloads dependencies." >&2
  exit 1
fi

mkdir -p "$VERIFY/videos" "$VERIFY/screenshots"
python3 "$VERIFY/test_isolated_verifier.py"
python3 "$VERIFY/test_task_project_fields.py"
python3 "$VERIFY/test_durable_control_queue.py"
python3 "$VERIFY/test_board_export_persistence.py"
python3 "$VERIFY/test_project_context.py"
python3 "$VERIFY/test_memory_gateway.py"
python3 "$VERIFY/test_memory_profile.py"
python3 "$VERIFY/test_memory_activation_e2e.py"
python3 "$VERIFY/test_taskspec_spawn.py"
python3 "$VERIFY/test_project_workspace.py"
python3 "$VERIFY/test_project_publisher.py"
python3 "$VERIFY/test_windows_publisher_bridge.py"
npm test --prefix "$ROOT/memory-gateway"
python3 "$VERIFY/test_task_evidence.py"
python3 "$VERIFY/test_windows_dictation_only.py"
python3 "$VERIFY/test_local_default_network.py"
python3 "$VERIFY/test_scorpion_theme.py"
python3 "$VERIFY/test_windows_launcher.py"
python3 "$VERIFY/test_windows_memory.py"
python3 "$VERIFY/test_provider_profiles.py"
python3 "$VERIFY/test_provider_session.py"
python3 "$VERIFY/test_windows_provider_profiles.py"
python3 "$VERIFY/test_worker_handoff.py"
python3 "$VERIFY/test_priorities_terminal_popup.py"
python3 "$VERIFY/test_public_repository.py"
python3 "$VERIFY/test_docker_persistence.py"
python3 "$VERIFY/test_runtime_supervisor.py"
python3 "$VERIFY/test_runtime_image_contract.py"
node "$VERIFY/test_todos_text_classification.js"
node "$VERIFY/test_browser_error_filter.js"
exec python3 "$VERIFY/core_verify.py"
