#!/usr/bin/env bash
# FIO Orchestrator — one-time setup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== FIO Orchestrator Setup ==="

# ── Python deps ────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found"; exit 1
fi

VENV="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV" ]; then
  echo "Creating Python venv..."
  python3 -m venv "$VENV"
fi

echo "Installing Python dependencies..."
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r requirements.txt

# ── Node.js / npm ─────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  echo "WARNING: node not found — skipping frontend build."
  echo "Install Node.js 18+ and run: cd frontend && npm install && npm run build"
  exit 0
fi

echo "Installing frontend dependencies..."
cd frontend
npm install --silent

echo "Building frontend..."
npm run build

cd "$SCRIPT_DIR"

echo ""
echo "=== Setup complete! ==="
echo "Run with:  ./run.sh"
echo "Or:        ./run.sh --port 8080"
