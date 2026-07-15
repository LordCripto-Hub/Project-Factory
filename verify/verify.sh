#!/bin/bash
set -euo pipefail
ROOT=${INSTALL_DIR:-$HOME/mypeople}
VERIFY="$ROOT/verify"
export INSTALL_DIR="$ROOT" PYTHONPATH="$ROOT/bin" PATH="$HOME/.local/bin:$ROOT/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
test -r "$HOME/.config/mypeople/queue.env"
set -a
. "$HOME/.config/mypeople/queue.env"
set +a

need=()
for c in curl jq git tmux node npm ss ffmpeg; do command -v "$c" >/dev/null 2>&1 || need+=("$c"); done
if ((${#need[@]})); then
  sudo -n apt-get update -qq
  sudo -n apt-get install -y -qq curl jq git tmux nodejs npm iproute2 ffmpeg
fi
mkdir -p "$VERIFY/videos" "$VERIFY/screenshots"
if [[ ! -d "$VERIFY/node_modules/playwright" ]]; then
  (cd "$VERIFY" && npm install --no-audit --no-fund playwright@1.61.1)
fi
(cd "$VERIFY" && npx playwright install chromium webkit >/dev/null)
python3 "$VERIFY/test_task_project_fields.py"
python3 "$VERIFY/test_project_context.py"
python3 "$VERIFY/test_memory_gateway.py"
python3 "$VERIFY/test_taskspec_spawn.py"
npm test --prefix "$ROOT/memory-gateway"
python3 "$VERIFY/test_task_evidence.py"
python3 "$VERIFY/test_voice_dock.py"
python3 "$VERIFY/test_scorpion_theme.py"
python3 "$VERIFY/test_windows_launcher.py"
python3 "$VERIFY/test_provider_profiles.py"
python3 "$VERIFY/test_provider_session.py"
python3 "$VERIFY/test_windows_provider_profiles.py"
python3 "$VERIFY/test_worker_handoff.py"
python3 "$VERIFY/test_priorities_terminal_popup.py"
python3 "$VERIFY/test_public_repository.py"
python3 "$VERIFY/test_docker_persistence.py"
node --check "$ROOT/bin/voice-dock.js"
node "$VERIFY/test_browser_error_filter.js"
exec python3 "$VERIFY/core_verify.py"
