#!/usr/bin/env bash
# macOS equivalent of view_today.bat. Prints today's daily pick dashboard.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec ./.venv/bin/python daily_view.py "$@"
