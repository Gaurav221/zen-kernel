#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if present
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi

HOST="${FIO_HOST:-0.0.0.0}"
PORT="${FIO_PORT:-8080}"
RELOAD="${FIO_RELOAD:-}"

ARGS="--host $HOST --port $PORT"
[[ -n "$RELOAD" ]] && ARGS="$ARGS --reload"

echo "Starting FIO Workload Analyzer on http://${HOST}:${PORT}"
echo "UI: http://localhost:${PORT}/ui/index.html"
echo "API docs: http://localhost:${PORT}/docs"
echo ""

exec uvicorn backend.main:app $ARGS
