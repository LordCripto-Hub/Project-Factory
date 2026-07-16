#!/bin/bash
set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
COMPOSE="$SCRIPT_DIR/compose.isolated.yml"
IMAGE=${MYPEOPLE_VERIFY_IMAGE:-mypeople-node:integration-a54d9e3}
TIMEOUT_SECONDS=${MP_VERIFY_TIMEOUT_SECONDS:-1800}
EVIDENCE_BASE=${MP_VERIFY_EVIDENCE_ROOT:-${TMPDIR:-/tmp}/mypeople-verify}
SMOKE_COMMAND=""
SOURCE_MODE=host
while (($#)); do
  case "$1" in
    --packaged-source)
      SOURCE_MODE=packaged
      shift
      ;;
    --smoke-command)
      if [[ $# -lt 2 || -z $2 ]]; then
        printf 'Usage: %s [--packaged-source] [--smoke-command COMMAND]\n' "$0" >&2
        exit 125
      fi
      SMOKE_COMMAND=$2
      shift 2
      ;;
    *)
      printf 'Usage: %s [--packaged-source] [--smoke-command COMMAND]\n' "$0" >&2
      exit 125
      ;;
  esac
done
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM"
PROJECT="mypeople-verify-${RUN_ID,,}"
RUN_DIR="$EVIDENCE_BASE/$RUN_ID"
OUTPUT="$RUN_DIR/verify.log"
RESULT=125
CLEANED=0
mkdir -p "$RUN_DIR"
: >"$OUTPUT"

cleanup() {
  local rc=0
  (( CLEANED )) && return 0
  CLEANED=1
  docker compose --project-name "$PROJECT" -f "$COMPOSE" down --remove-orphans --timeout 10 >>"$OUTPUT" 2>&1 || rc=$?
  return "$rc"
}

fallback_cleanup() {
  cleanup || true
}
trap fallback_cleanup EXIT INT TERM

fail_host() {
  printf 'Isolated verifier host error: %s\n' "$1" >&2
  RESULT=125
}

if ! [[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  fail_host "MP_VERIFY_TIMEOUT_SECONDS must be a positive integer"
elif ! command -v docker >/dev/null 2>&1; then
  fail_host "docker is required"
elif ! command -v timeout >/dev/null 2>&1; then
  fail_host "the coreutils timeout command is required"
elif ! docker compose version >/dev/null 2>&1; then
  fail_host "Docker Compose v2 is required"
else
  export MYPEOPLE_VERIFY_IMAGE="$IMAGE"
  export MP_VERIFY_SOURCE="$ROOT"
  export MP_VERIFY_EVIDENCE_DIR="$RUN_DIR"
  export MP_VERIFY_SOURCE_MODE="$SOURCE_MODE"
  export MP_VERIFY_MODE=full MP_VERIFY_SMOKE_COMMAND=""
  if [[ -n $SMOKE_COMMAND ]]; then
    export MP_VERIFY_MODE=smoke MP_VERIFY_SMOKE_COMMAND="$SMOKE_COMMAND"
  fi

  if docker compose --project-name "$PROJECT" -f "$COMPOSE" config --quiet >>"$OUTPUT" 2>&1; then
    timeout --foreground "${TIMEOUT_SECONDS}s" \
      docker compose --project-name "$PROJECT" -f "$COMPOSE" run --rm --no-deps verify \
      >>"$OUTPUT" 2>&1
    run_rc=$?
    case "$run_rc" in
      0) RESULT=0 ;;
      124) RESULT=124 ;;
      125|126|127) RESULT=125 ;;
      *) RESULT=1 ;;
    esac
  else
    RESULT=125
  fi

  if (( RESULT != 0 )); then
    docker compose --project-name "$PROJECT" -f "$COMPOSE" ps --all >>"$RUN_DIR/compose-ps.log" 2>&1 || true
    docker compose --project-name "$PROJECT" -f "$COMPOSE" logs --no-color >>"$RUN_DIR/compose.log" 2>&1 || true
  fi
fi

cleanup_rc=0
cleanup || cleanup_rc=$?
trap - EXIT INT TERM
if (( cleanup_rc != 0 && RESULT == 0 )); then
  RESULT=125
fi

if [[ -f "$OUTPUT" ]]; then
  sed -n '1,4000p' "$OUTPUT"
fi
if (( RESULT == 0 )); then
  rm -rf -- "$RUN_DIR"
  rmdir --ignore-fail-on-non-empty "$EVIDENCE_BASE" 2>/dev/null || true
  printf 'Isolated MyPeople verification passed.\n'
else
  printf 'Isolated MyPeople verification failed with exit %s. Evidence retained at: %s\n' "$RESULT" "$RUN_DIR" >&2
fi
exit "$RESULT"
