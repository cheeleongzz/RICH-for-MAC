#!/usr/bin/env bash
# Uninstall the RICH daily launchd agent on macOS.
set -euo pipefail

LABEL="com.user.rich.daily"
PLIST_DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
uid="$(id -u)"

if launchctl print "gui/${uid}/${LABEL}" >/dev/null 2>&1; then
    if ! launchctl bootout "gui/${uid}/${LABEL}" 2>/dev/null; then
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
    fi
    echo "removed: $LABEL"
else
    echo "not loaded: $LABEL"
fi

if [ -f "$PLIST_DEST" ]; then
    rm -f "$PLIST_DEST"
    echo "deleted: $PLIST_DEST"
else
    echo "not found: $PLIST_DEST"
fi
