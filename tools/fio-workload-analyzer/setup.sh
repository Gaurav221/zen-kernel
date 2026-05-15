#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== FIO Workload Analyzer Setup ==="

# ── Python venv ──────────────────────────────────────────────────────────── #
if [[ ! -d .venv ]]; then
  echo "[1/4] Creating Python virtual environment…"
  python3 -m venv .venv
else
  echo "[1/4] Virtual environment exists, skipping."
fi

source .venv/bin/activate

# ── Dependencies ─────────────────────────────────────────────────────────── #
echo "[2/4] Installing Python dependencies…"
pip install --upgrade pip -q
pip install -r requirements.txt -q

# ── System tool checks ───────────────────────────────────────────────────── #
echo "[3/4] Checking system tools…"
MISSING=()

command -v fio      &>/dev/null || MISSING+=("fio")
command -v nvme     &>/dev/null || MISSING+=("nvme-cli")
command -v iostat   &>/dev/null || MISSING+=("sysstat (iostat)")
command -v lsblk    &>/dev/null || MISSING+=("util-linux (lsblk)")

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "  ⚠  Missing tools (install for full functionality):"
  for t in "${MISSING[@]}"; do
    echo "       • $t"
  done
  echo "  Install with:  sudo apt install fio nvme-cli sysstat util-linux"
else
  echo "  ✓ All system tools found."
fi

# ── Data directories ─────────────────────────────────────────────────────── #
echo "[4/4] Creating data directories…"
mkdir -p data/{logs,results,exports,plots,fio_jobs,models}

echo ""
echo "Setup complete! Run the analyzer with:  ./run.sh"
echo "Or manually:  source .venv/bin/activate && uvicorn backend.main:app --reload"
