#!/usr/bin/env bash
# Run both backend services (FastAPI + LiveKit worker) with colored logs.
# Usage:
#   bash scripts/run.sh                  # backend + worker
#   bash scripts/run.sh --with-frontend  # backend + worker + frontend
#   bash scripts/run.sh --backend-only
#   bash scripts/run.sh --worker-only
#   npm run dev          # via package.json -> python scripts/run.py
#   npm run dev:all      # with frontend
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

WITH_FRONTEND=false
BACKEND_ONLY=false
WORKER_ONLY=false
FRONTEND_ONLY=false
WORKER_MODE="dev"

for arg in "$@"; do
  case "$arg" in
    --with-frontend|-f) WITH_FRONTEND=true ;;
    --backend-only) BACKEND_ONLY=true ;;
    --worker-only) WORKER_ONLY=true ;;
    --frontend-only) FRONTEND_ONLY=true ;;
    --worker-mode=*) WORKER_MODE="${arg#*=}" ;;
    --help|-h)
      echo "Usage: $0 [--with-frontend] [--backend-only] [--worker-only] [--frontend-only] [--worker-mode=dev|start]"
      exit 0
      ;;
  esac
done

# Handle exclusive modes
if [[ "$FRONTEND_ONLY" == true ]]; then
  WITH_FRONTEND=false
  BACKEND_ONLY=false
  WORKER_ONLY=false
  RUN_BACKEND=false
  RUN_WORKER=false
  RUN_FRONTEND=true
elif [[ "$BACKEND_ONLY" == true ]]; then
  RUN_BACKEND=true
  RUN_WORKER=false
  RUN_FRONTEND=false
elif [[ "$WORKER_ONLY" == true ]]; then
  RUN_BACKEND=false
  RUN_WORKER=true
  RUN_FRONTEND=false
else
  RUN_BACKEND=true
  RUN_WORKER=true
  RUN_FRONTEND=$WITH_FRONTEND
  if [[ "$FRONTEND_ONLY" == true ]]; then RUN_FRONTEND=true; fi
fi

# Prefer uv if available (use --active to avoid VIRTUAL_ENV mismatch)
if command -v uv &>/dev/null; then
  BACKEND_CMD=(uv run --active python server.py)
  WORKER_CMD=(uv run --active python "livekit_worker.py" "$WORKER_MODE")
else
  BACKEND_CMD=(python server.py)
  WORKER_CMD=(python "livekit_worker.py" "$WORKER_MODE")
fi

if command -v pnpm &>/dev/null; then
  FRONTEND_CMD=(pnpm dev)
else
  FRONTEND_CMD=(npm run dev)
fi

# Colors (use $'' for proper ESC)
C_BACKEND=$'\033[38;5;208m'
C_WORKER=$'\033[38;5;39m'
C_FRONTEND=$'\033[38;5;114m'
C_RESET=$'\033[0m'
C_DIM=$'\033[2m'

pids=()

cleanup() {
  echo -e "\n${C_DIM}Shutting down...${C_RESET}"
  for pid in "${pids[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
  for pid in "${pids[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Helper to prefix logs
run_with_prefix() {
  local name="$1"; shift
  local color="$1"; shift
  local cwd="$1"; shift
  # Use unbuffered output; unset VIRTUAL_ENV to avoid uv warning
  (cd "$cwd" && PYTHONUNBUFFERED=1 VIRTUAL_ENV="" "$@" 2>&1 | sed -u "s/^/${color}[${name}]${C_RESET} /") &
  pids+=($!)
}

has_livekit_config() {
  local url="${LIVEKIT_URL:-}"
  if [[ -z "$url" ]]; then
    # check .env files
    if [[ -f "$ROOT/.env" ]]; then
      url=$(grep -E "^LIVEKIT_URL=" "$ROOT/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" | xargs) || true
    fi
    if [[ -z "$url" && -f "$BACKEND_DIR/.env" ]]; then
      url=$(grep -E "^LIVEKIT_URL=" "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" | xargs) || true
    fi
  fi
  if [[ -z "$url" ]]; then return 1; fi
  if [[ "$url" == *"your-project"* ]] || [[ "$url" == *"placeholder"* ]]; then return 1; fi
  return 0
}

echo -e "${C_DIM}voice-agent runner — root=$ROOT${C_RESET}"
# Env warnings (simple)
if [[ -z "${DEEPGRAM_API_KEY:-}" ]] && ! grep -q "DEEPGRAM_API_KEY" "$ROOT/.env" 2>/dev/null; then
  echo -e "\033[33m[warn] DEEPGRAM_API_KEY not set — STT/TTS will fail\033[0m"
fi
if ! grep -q "LIVEKIT_URL" "$ROOT/.env" 2>/dev/null && [[ -z "${LIVEKIT_URL:-}" ]]; then
  echo -e "\033[33m[warn] LIVEKIT_URL not set — LiveKit will fallback to Direct WS bridge\033[0m"
fi
if [[ -z "${XAI_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]] && ! grep -q "XAI_API_KEY" "$ROOT/.env" 2>/dev/null && ! grep -q "OPENAI_API_KEY" "$ROOT/.env" 2>/dev/null; then
  echo -e "\033[33m[warn] Neither XAI_API_KEY nor OPENAI_API_KEY set — LLM will use LiveKit Inference\033[0m"
fi

if [[ "$RUN_BACKEND" == true ]]; then
  echo -e "${C_DIM}→ starting backend: ${BACKEND_CMD[*]} (cwd=backend)${C_RESET}"
  run_with_prefix "backend" "$C_BACKEND" "$BACKEND_DIR" "${BACKEND_CMD[@]}"
  # wait for backend /api/info (max 25s)
  echo -e "${C_DIM}  waiting for http://localhost:7777/api/info ...${C_RESET}"
  for i in {1..25}; do
    if curl -sf http://localhost:7777/api/info >/dev/null 2>&1; then
      echo -e "${C_DIM}✓ backend ready${C_RESET}"
      break
    fi
    sleep 1
  done
fi

if [[ "$RUN_WORKER" == true ]]; then
  if ! has_livekit_config; then
    echo -e "${C_WORKER}[worker]${C_RESET} Skipping LiveKit worker — LIVEKIT_URL not configured. Backend alone handles voice via /ws/voice (Direct WS bridge)."
    echo -e "${C_DIM}         To enable LiveKit: set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in .env, then rerun.${C_RESET}"
    RUN_WORKER=false
  else
    # small delay so backend is ready
    [[ "$RUN_BACKEND" == true ]] && sleep 1.5
    echo -e "${C_DIM}→ starting worker: ${WORKER_CMD[*]} (cwd=backend)${C_RESET}"
    run_with_prefix "worker" "$C_WORKER" "$BACKEND_DIR" "${WORKER_CMD[@]}"
  fi
fi

if [[ "$RUN_FRONTEND" == true ]]; then
  echo -e "${C_DIM}→ starting frontend: ${FRONTEND_CMD[*]} (cwd=frontend)${C_RESET}"
  run_with_prefix "frontend" "$C_FRONTEND" "$FRONTEND_DIR" "${FRONTEND_CMD[@]}"
fi

if [[ ${#pids[@]} -eq 0 ]]; then
  if [[ "$WORKER_ONLY" == true ]]; then
    echo -e "\033[31m[error] LIVEKIT_URL is required for worker-only mode. Set it in .env.\033[0m"
    exit 1
  fi
  echo "Nothing to run. Use --help"
  exit 1
fi

echo ""
echo "============================================================"
echo "  Voice Agent — services running"
[[ "$RUN_BACKEND" == true ]] && echo "  • Backend (FastAPI + Deepgram Flux) → http://localhost:7777  (/api/info, /docs, /ws/voice)"
[[ "$RUN_WORKER" == true ]] && echo "  • LiveKit worker (flux-brooke-en)     → mode=$WORKER_MODE  (joining LiveKit rooms)"
[[ "$RUN_FRONTEND" == true ]] && echo "  • Frontend (Next.js)                  → http://localhost:3000"
if [[ "$RUN_BACKEND" == true && "$RUN_WORKER" == false ]]; then
  echo "  • LiveKit worker — skipped (no LIVEKIT_URL, Direct WS bridge active)"
fi
echo "  Stop: Ctrl+C"
echo "============================================================"
echo ""

# Wait for all — backend is critical but worker is optional:
# If worker exits early (e.g., no LIVEKIT_URL), backend keeps running.
# `wait` waits for all pids; trap handles Ctrl+C.
wait
EXIT_CODE=$?
# If we reach here, all services exited; if backend was running and worker died first, `wait` would have waited for backend too.
# No extra cleanup needed — trap will run on exit.
