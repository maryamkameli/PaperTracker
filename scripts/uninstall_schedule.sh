#!/bin/bash
# Stop the morning run. Your lists and PDFs stay where they are.
set -euo pipefail
LABEL="com.$(id -un).papertracker"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Removed the daily schedule."
