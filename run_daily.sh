#!/usr/bin/env bash
# macOS equivalent of run_daily.bat. Invoked manually or by the launchd agent.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec ./.venv/bin/python run_daily.py "$@"
