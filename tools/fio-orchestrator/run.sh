#!/usr/bin/env bash
# FIO Orchestrator — start the server
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${1:-8000}"
PORT="${PORT//--port=/}"
HOST="${2:-0.0.0.0}"

VENV="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV" ]; then
  echo "Venv not found. Run ./setup.sh first."
  exit 1
fi

export FIO_DB="${FIO_DB:-$SCRIPT_DIR/fio_orchestrator.db}"

echo "Starting FIO Orchestrator on http://localhost:$PORT"
echo "Database: $FIO_DB"
echo ""

"$VENV/bin/uvicorn" backend.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --reload \
  --reload-dir "$SCRIPT_DIR/backend"
