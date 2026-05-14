#!/usr/bin/env bash
# Install the RICH daily launchd agent on macOS.
#
# Mirrors scripts/install_scheduler.ps1 (Windows) — installs two daily triggers:
#   primary  : 08:00 MYT (Asia/Kuala_Lumpur)
#   fallback : 12:00 MYT
#
# MYT trigger times are converted to local-tz hours at install time. If the
# machine's timezone changes (e.g., travel), re-run this script to re-render
# the plist with the new local offsets.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$PROJECT_DIR/scripts/com.user.rich.daily.plist.template"
LABEL="com.user.rich.daily"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [ ! -f "$TEMPLATE" ]; then
    echo "error: template missing at $TEMPLATE" >&2
    exit 1
fi

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
    echo "error: $PROJECT_DIR/.venv/bin/python not found." >&2
    echo "       run scripts/bootstrap_venv.sh first." >&2
    exit 1
fi

mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$HOME/Library/LaunchAgents"

# Convert 08:00 and 12:00 MYT to local-tz HH:MM using a fixed reference date
# (today, UTC-anchored) so DST offsets are correct for the install moment.
ref_date="$(date -u +%Y-%m-%d)"
primary_local=$(TZ=":$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || echo UTC)" \
    date -j -f "%Y-%m-%d %H:%M %Z" "${ref_date} 08:00 MYT" "+%H:%M" 2>/dev/null || true)
fallback_local=$(TZ=":$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || echo UTC)" \
    date -j -f "%Y-%m-%d %H:%M %Z" "${ref_date} 12:00 MYT" "+%H:%M" 2>/dev/null || true)

# Portable fallback via python (always available — we just bootstrapped venv).
if [ -z "$primary_local" ] || [ -z "$fallback_local" ]; then
    read -r primary_local fallback_local <<EOF
$("$PROJECT_DIR/.venv/bin/python" - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
myt = ZoneInfo("Asia/Kuala_Lumpur")
local = datetime.now().astimezone().tzinfo
today = datetime.now(myt).date()
def to_local(h, m):
    dt = datetime(today.year, today.month, today.day, h, m, tzinfo=myt)
    return dt.astimezone(local).strftime("%H:%M")
print(to_local(8, 0), to_local(12, 0))
PY
)
EOF
fi

primary_hour="${primary_local%%:*}"
primary_minute="${primary_local##*:}"
fallback_hour="${fallback_local%%:*}"
fallback_minute="${fallback_local##*:}"

# Strip any leading zero so plist <integer> parses cleanly (08 → 8).
primary_hour=$((10#$primary_hour))
primary_minute=$((10#$primary_minute))
fallback_hour=$((10#$fallback_hour))
fallback_minute=$((10#$fallback_minute))

echo "MYT 08:00 -> local ${primary_hour}:$(printf %02d "$primary_minute")"
echo "MYT 12:00 -> local ${fallback_hour}:$(printf %02d "$fallback_minute")"

sed \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    -e "s|__PRIMARY_HOUR__|${primary_hour}|g" \
    -e "s|__PRIMARY_MINUTE__|${primary_minute}|g" \
    -e "s|__FALLBACK_HOUR__|${fallback_hour}|g" \
    -e "s|__FALLBACK_MINUTE__|${fallback_minute}|g" \
    "$TEMPLATE" > "$PLIST_DEST"

echo "wrote $PLIST_DEST"

uid="$(id -u)"
# Replace any existing agent — bootout is idempotent for our purposes.
launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null || true

if ! launchctl bootstrap "gui/${uid}" "$PLIST_DEST" 2>/dev/null; then
    # Older macOS (10.10 and below) — fall back to load.
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    launchctl load "$PLIST_DEST"
fi

echo ""
echo "installed launchd agent: $LABEL"
launchctl print "gui/${uid}/${LABEL}" 2>/dev/null | grep -E '(state|next fire|program)' || true
echo ""
echo "trigger manually with: launchctl kickstart gui/${uid}/${LABEL}"
echo "uninstall with:        bash scripts/uninstall_scheduler.sh"
