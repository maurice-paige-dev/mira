#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Install the MLOps data-ingest watcher as a launchd service
# (macOS only).
#
# Usage:
#   ./scripts/install-watcher.sh            # install + start
#   ./scripts/install-watcher.sh --uninstall
#   ./scripts/install-watcher.sh --status
# ─────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_DEST="$HOME/Library/LaunchAgents/com.ecommerce.ingest-watcher.plist"
PLIST_SRC="$SCRIPT_DIR/scripts/com.ecommerce.ingest-watcher.plist"

info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[OK]\033[0m $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; }

case "${1:-install}" in
  --uninstall|-u)
    info "Uninstalling watcher service\u2026"
    if [ -f "$PLIST_DEST" ]; then
      launchctl unload "$PLIST_DEST" 2>/dev/null || true
      rm "$PLIST_DEST"
      ok "Unloaded and removed plist."
    else
      info "No plist found at $PLIST_DEST"
    fi
    exit 0
    ;;
  --status|-s)
    if [ -f "$PLIST_DEST" ]; then
      launchctl list com.ecommerce.ingest-watcher 2>/dev/null && \
        ok "Service is loaded" || \
        info "Plist exists but service is not loaded"
    else
      info "Service is not installed"
    fi
    exit 0
    ;;
  --help|-h)
    echo "Usage: $0 [--install|--uninstall|--status]"
    exit 0
    ;;
esac

mkdir -p "$SCRIPT_DIR/logs"

# ── Install ─────────────────────────────────────────────────
PYTHON_PATH="$(command -v python3)"
info "Installing plist to $PLIST_DEST\u2026"
sed -e "s|__PROJECT__|${SCRIPT_DIR}|g" \
    -e "s|__PYTHON__|${PYTHON_PATH}|g" \
    "$PLIST_SRC" > "$PLIST_DEST"

info "Loading service\u2026"
launchctl load "$PLIST_DEST"

ok "Watcher service installed and started!"
echo ""
echo "  Logs:        $SCRIPT_DIR/logs/watcher.log"
echo "  Error log:   $SCRIPT_DIR/logs/watcher-error.log"
echo "  Drop files:  $SCRIPT_DIR/data/ingest/"
echo ""
echo "Commands:"
echo "  tail -f $SCRIPT_DIR/logs/watcher.log"
echo "  $0 --uninstall   # stop + remove"
echo "  $0 --status      # check status"
