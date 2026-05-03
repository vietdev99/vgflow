#!/usr/bin/env bash
# Run a bounded Codex child process for VGFlow workflows.
#
# This helper exists because Claude's Task(...) primitive and Codex's
# subprocess model are not equivalent. VGFlow uses this wrapper where exact
# model tier, timeout, output file, and optional schema control matter.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: codex-spawn.sh --prompt-file FILE --out FILE [options]

Options:
  --tier planner|executor|scanner|adversarial
  --model MODEL (default: Codex config model unless VG_CODEX_MODEL_* is set)
  --prompt-file FILE
  --out FILE
  --timeout SECONDS
  --sandbox read-only|workspace-write|danger-full-access
  --cd DIR
  --schema FILE
  --spawn-role ROLE
  --spawn-id ID
  --task-id TASK_ID
  --wave WAVE_ID
  -h, --help
EOF
}

TIER="executor"
MODEL=""
PROMPT_FILE=""
OUT_FILE=""
TIMEOUT_SECONDS="900"
SANDBOX_MODE="${CODEX_SANDBOX:-workspace-write}"
WORKDIR="$(pwd)"
SCHEMA_FILE=""
SPAWN_ROLE=""
SPAWN_ID=""
TASK_ID=""
WAVE_ID=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tier)
      TIER="${2:-}"
      shift 2
      ;;
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --prompt-file)
      PROMPT_FILE="${2:-}"
      shift 2
      ;;
    --out)
      OUT_FILE="${2:-}"
      shift 2
      ;;
    --timeout)
      TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --sandbox)
      SANDBOX_MODE="${2:-}"
      shift 2
      ;;
    --cd)
      WORKDIR="${2:-}"
      shift 2
      ;;
    --schema|--output-schema)
      SCHEMA_FILE="${2:-}"
      shift 2
      ;;
    --spawn-role)
      SPAWN_ROLE="${2:-}"
      shift 2
      ;;
    --spawn-id)
      SPAWN_ID="${2:-}"
      shift 2
      ;;
    --task-id)
      TASK_ID="${2:-}"
      shift 2
      ;;
    --wave)
      WAVE_ID="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

model_for_tier() {
  # Do not hardcode a default model. Codex model availability differs between
  # ChatGPT and API-backed accounts; unset means "use Codex config default".
  case "$1" in
    planner) echo "${VG_CODEX_MODEL_PLANNER:-}" ;;
    executor) echo "${VG_CODEX_MODEL_EXECUTOR:-}" ;;
    scanner) echo "${VG_CODEX_MODEL_SCANNER:-}" ;;
    adversarial) echo "${VG_CODEX_MODEL_ADVERSARIAL:-}" ;;
    *)
      echo "ERROR: unknown tier: $1" >&2
      return 2
      ;;
  esac
}

if [ -z "$MODEL" ]; then
  MODEL="$(model_for_tier "$TIER")"
fi

case "$SANDBOX_MODE" in
  read-only|workspace-write|danger-full-access) ;;
  *)
    echo "ERROR: invalid sandbox mode: $SANDBOX_MODE" >&2
    exit 2
    ;;
esac

case "$TIMEOUT_SECONDS" in
  ''|*[!0-9]*)
    echo "ERROR: --timeout must be an integer number of seconds" >&2
    exit 2
    ;;
esac

if [ -z "$PROMPT_FILE" ] || [ ! -s "$PROMPT_FILE" ]; then
  echo "ERROR: --prompt-file is required and must be non-empty" >&2
  exit 2
fi

if [ -z "$OUT_FILE" ]; then
  echo "ERROR: --out is required" >&2
  exit 2
fi

if [ ! -d "$WORKDIR" ]; then
  echo "ERROR: --cd directory does not exist: $WORKDIR" >&2
  exit 2
fi

if [ -n "$SCHEMA_FILE" ] && [ ! -f "$SCHEMA_FILE" ]; then
  echo "ERROR: --schema file does not exist: $SCHEMA_FILE" >&2
  exit 2
fi

command -v codex >/dev/null 2>&1 || {
  echo "ERROR: codex CLI not found in PATH" >&2
  exit 127
}

REPO_ROOT_FOR_SPAWN="$WORKDIR"
if command -v git >/dev/null 2>&1; then
  if GIT_ROOT="$(git -C "$WORKDIR" rev-parse --show-toplevel 2>/dev/null)"; then
    REPO_ROOT_FOR_SPAWN="$GIT_ROOT"
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SPAWN_RECORD_SCRIPT="${REPO_ROOT_FOR_SPAWN}/.claude/scripts/codex-spawn-record.py"
if [ ! -f "$SPAWN_RECORD_SCRIPT" ]; then
  SPAWN_RECORD_SCRIPT="${REPO_ROOT_FOR_SPAWN}/scripts/codex-spawn-record.py"
fi
if [ ! -f "$SPAWN_RECORD_SCRIPT" ]; then
  SPAWN_RECORD_SCRIPT="${SCRIPT_DIR}/../../../../scripts/codex-spawn-record.py"
fi
if [ -n "$SPAWN_ROLE" ]; then
  if [ ! -f "$SPAWN_RECORD_SCRIPT" ]; then
    echo "ERROR: codex-spawn-record.py missing; cannot record required spawn evidence" >&2
    exit 2
  fi
  python3 "$SPAWN_RECORD_SCRIPT" preflight \
    --repo-root "$REPO_ROOT_FOR_SPAWN" \
    --role "$SPAWN_ROLE" \
    --spawn-id "${SPAWN_ID:-}" \
    --task-id "${TASK_ID:-}" \
    --wave-id "${WAVE_ID:-}" \
    --prompt-file "$PROMPT_FILE"
fi

TIMEOUT_BIN="${VG_TIMEOUT_BIN:-}"
if [ -z "$TIMEOUT_BIN" ]; then
  TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
fi
if [ -z "$TIMEOUT_BIN" ]; then
  echo "ERROR: timeout/gtimeout command not found; install GNU coreutils/Git Bash" >&2
  exit 127
fi

mkdir -p "$(dirname "$OUT_FILE")"

STDOUT_LOG="${OUT_FILE}.stdout.log"
STDERR_LOG="${OUT_FILE}.stderr.log"
EXIT_FILE="${OUT_FILE}.exit"
TMP_OUT="${OUT_FILE}.tmp.$$"
rm -f "$TMP_OUT"

CODEX_ARGS=(
  exec
  --sandbox "$SANDBOX_MODE"
  --cd "$WORKDIR"
  --output-last-message "$TMP_OUT"
)

if [ -n "$MODEL" ]; then
  CODEX_ARGS+=(--model "$MODEL")
fi

if [ -n "$SCHEMA_FILE" ]; then
  CODEX_ARGS+=(--output-schema "$SCHEMA_FILE")
fi

set +e
"$TIMEOUT_BIN" "${TIMEOUT_SECONDS}s" codex "${CODEX_ARGS[@]}" - < "$PROMPT_FILE" \
  > "$STDOUT_LOG" 2> "$STDERR_LOG"
EXIT_CODE=$?
set -e

printf '%s\n' "$EXIT_CODE" > "$EXIT_FILE"

if [ "$EXIT_CODE" -ne 0 ]; then
  rm -f "$TMP_OUT"
  if [ "$EXIT_CODE" -eq 124 ] || [ "$EXIT_CODE" -eq 137 ]; then
    echo "ERROR: codex child timed out after ${TIMEOUT_SECONDS}s (tier=$TIER model=$MODEL)" >&2
  else
    echo "ERROR: codex child failed with exit $EXIT_CODE (tier=$TIER model=$MODEL)" >&2
  fi
  echo "stderr: $STDERR_LOG" >&2
  echo "stdout: $STDOUT_LOG" >&2
  exit "$EXIT_CODE"
fi

if [ ! -s "$TMP_OUT" ]; then
  rm -f "$TMP_OUT"
  echo "ERROR: codex child produced empty final message" >&2
  echo "stderr: $STDERR_LOG" >&2
  echo "stdout: $STDOUT_LOG" >&2
  exit 1
fi

mv "$TMP_OUT" "$OUT_FILE"

if [ -n "$SPAWN_ROLE" ]; then
  python3 "$SPAWN_RECORD_SCRIPT" record \
    --repo-root "$REPO_ROOT_FOR_SPAWN" \
    --role "$SPAWN_ROLE" \
    --spawn-id "${SPAWN_ID:-}" \
    --task-id "${TASK_ID:-}" \
    --wave-id "${WAVE_ID:-}" \
    --prompt-file "$PROMPT_FILE" \
    --out-file "$OUT_FILE" \
    --stdout-log "$STDOUT_LOG" \
    --stderr-log "$STDERR_LOG" \
    --exit-code "$EXIT_CODE" \
    --tier "$TIER" \
    --model "$MODEL" \
    --sandbox "$SANDBOX_MODE"
fi
echo "codex child complete: $OUT_FILE"
