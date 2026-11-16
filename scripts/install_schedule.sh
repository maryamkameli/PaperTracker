#!/bin/bash
# Run PaperTracker every morning with launchd. If the Mac is asleep at that time,
# macOS runs the job as soon as it wakes up.
#   scripts/install_schedule.sh          # 6:15 am
#   scripts/install_schedule.sh 7 5      # 7:05 am
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || { echo "Run scripts/setup.sh first."; exit 1; }

HOUR="${1:-6}"
MINUTE="${2:-15}"
LABEL="com.$(id -un).papertracker"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/PaperTracker.log"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>-m</string><string>papertracker</string><string>run</string>
    <string>--config</string><string>$REPO/topics.toml</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST_END

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

printf 'Scheduled for %d:%02d every day. Log: %s\n\n' "$HOUR" "$MINUTE" "$LOG"
echo "One more step if your output folder is on the Desktop or in Documents:"
echo "macOS keeps background jobs out of those folders until you allow it."
echo "System Settings > Privacy & Security > Full Disk Access, click +, press Cmd+Shift+G and paste:"
(cd "$REPO" && "$PY" -c 'from papertracker.cli import python_paths; print("\n".join("  " + p for p in python_paths()))')
echo
echo "Try it right away:  launchctl kickstart gui/$(id -u)/$LABEL   then: tail $LOG"
