#!/usr/bin/env bash
# Bootstrap the RICH project venv on macOS.
#
# Creates ./.venv at the project root and installs requirements.txt into it.
# Idempotent: safe to re-run; will reuse an existing .venv and upgrade pip
# and dependencies in place.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 not found on PATH. Install via Homebrew (brew install python) or python.org." >&2
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Creating venv at $PROJECT_DIR/.venv ..."
    python3 -m venv .venv
fi

./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo ""
echo "venv ready at $PROJECT_DIR/.venv"
echo "next steps:"
echo "  1. cp .env.example .env   # then paste your FMP_API_KEY"
echo "  2. ./run_daily.sh         # run the pipeline once manually"
echo "  3. bash scripts/install_scheduler.sh   # install the launchd agent"
