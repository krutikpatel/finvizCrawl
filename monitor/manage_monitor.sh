#!/usr/bin/env bash
# Usage:
#   ./monitor/manage_monitor.sh install    — register and enable the launchd job
#   ./monitor/manage_monitor.sh uninstall  — stop and remove the launchd job
#   ./monitor/manage_monitor.sh run        — run the daily sentinel right now (foreground)
#   ./monitor/manage_monitor.sh status     — show whether the job is loaded
#   ./monitor/manage_monitor.sh logs       — tail today's monitor log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.finzwiz.monitor"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$PROJECT_DIR/logs"
TODAY="$(TZ='America/Los_Angeles' date +%Y-%m-%d)"

cmd="${1:-help}"

case "$cmd" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
    cp "$PLIST_SRC" "$PLIST_DEST"
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    launchctl load -w "$PLIST_DEST"
    echo "Installed: $PLIST_NAME"
    echo "Runs at:   8:00 AM daily (system local time)"
    echo "Logs:      $LOG_DIR/monitor-YYYY-MM-DD.log"
    ;;

  uninstall)
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    echo "Uninstalled: $PLIST_NAME"
    ;;

  run)
    echo "Running monitor now..."
    bash "$SCRIPT_DIR/scripts/run-daily.sh"
    ;;

  status)
    if launchctl list | grep -q "$PLIST_NAME"; then
        echo "LOADED — job is registered with launchd"
        launchctl list "$PLIST_NAME" 2>/dev/null || true
    else
        echo "NOT LOADED — run: ./monitor/manage_monitor.sh install"
    fi
    ;;

  logs)
    LOG_FILE="$LOG_DIR/monitor-$TODAY.log"
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "No log yet for $TODAY (expected at $LOG_FILE)"
    fi
    ;;

  *)
    echo "Usage: $0 {install|uninstall|run|status|logs}"
    exit 1
    ;;
esac
