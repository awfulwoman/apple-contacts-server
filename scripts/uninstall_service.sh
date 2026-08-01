#!/bin/bash
set -euo pipefail

PLIST_LABEL="com.awfulwoman.apple-contacts-server"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [ -f "$PLIST_PATH" ]; then
    launchctl bootout gui/$(id -u) "$PLIST_PATH" 2>/dev/null || launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm "$PLIST_PATH"
    echo "apple-contacts-server removed."
else
    echo "No service found at $PLIST_PATH"
fi
