#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Start the Shipping Cost Advisor Chatbot
# ─────────────────────────────────────────────────────────────
# Usage:
#   ./start_chatbot.sh              # Start both API and React dev server
#   ./start_chatbot.sh --api-only   # Start only the API server
#   ./start_chatbot.sh --react-only # Start only the React dev server
# ─────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

API_PORT="${API_PORT:-8000}"
REACT_PORT="${REACT_PORT:-5173}"

info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[OK]\033[0m $*"; }

# ── Check prerequisites ─────────────────────────────────
check_prereqs() {
  info "Checking prerequisites…"

  if ! command -v python3 &>/dev/null; then
    error "python3 is required but not found."
    exit 1
  fi

  if ! command -v node &>/dev/null; then
    error "node is required but not found."
    exit 1
  fi

  # Check for Python venv
  if [ ! -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    # Try to create it
    info "No .venv found. Creating one…"
    python3 -m venv "$SCRIPT_DIR/.venv"
  fi

  # Check for node_modules
  if [ ! -d "$SCRIPT_DIR/chatbot-frontend/node_modules" ]; then
    info "Installing React frontend dependencies…"
    cd "$SCRIPT_DIR/chatbot-frontend" && npm install
    cd "$SCRIPT_DIR"
  fi

  # Check for ChromaDB
  if [ ! -d "$SCRIPT_DIR/chroma_shipping_db" ]; then
    info "ChromaDB not found. Running RAG pipeline to build it…"
    source "$SCRIPT_DIR/.venv/bin/activate"
    pip install -q sentence-transformers chromadb pandas
    python "$SCRIPT_DIR/rag_shipping_advisor.py" --no-interactive 2>&1 || true
    ok "ChromaDB should be built now."
  fi

  ok "All prerequisites satisfied."
}

start_api() {
  info "Starting API server on port $API_PORT…"
  source "$SCRIPT_DIR/.venv/bin/activate"
  cd "$SCRIPT_DIR"
  # Install dependencies if not present
  pip install -q fastapi uvicorn sentence-transformers chromadb pandas 2>/dev/null || true
  uvicorn api_server:app --host 0.0.0.0 --port "$API_PORT" --reload &
  API_PID=$!
  ok "API server started (PID: $API_PID)"
  echo "$API_PID" > /tmp/chatbot_api.pid
}

start_react() {
  info "Starting React dev server on port $REACT_PORT…"
  cd "$SCRIPT_DIR/chatbot-frontend"
  npx vite --port "$REACT_PORT" --host &
  REACT_PID=$!
  ok "React dev server started (PID: $REACT_PID)"
  echo "$REACT_PID" > /tmp/chatbot_react.pid
}

cleanup() {
  echo ""
  info "Shutting down…"
  if [ -f /tmp/chatbot_api.pid ]; then
    kill "$(cat /tmp/chatbot_api.pid)" 2>/dev/null || true
    rm -f /tmp/chatbot_api.pid
  fi
  if [ -f /tmp/chatbot_react.pid ]; then
    kill "$(cat /tmp/chatbot_react.pid)" 2>/dev/null || true
    rm -f /tmp/chatbot_react.pid
  fi
  ok "Stopped."
}

trap cleanup EXIT INT TERM

# ── Parse args ──────────────────────────────────────────
MODE="both"
for arg in "$@"; do
  case "$arg" in
    --api-only) MODE="api" ;;
    --react-only) MODE="react" ;;
    --help)
      echo "Usage: $0 [--api-only | --react-only]"
      exit 0
      ;;
  esac
done

# ── Main ────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Shipping Cost Advisor - Chatbot Launcher          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

check_prereqs

case "$MODE" in
  both)
    start_api
    sleep 3
    start_react
    echo ""
    ok "Both servers are running!"
    echo "   API:     http://localhost:$API_PORT"
    echo "   React:   http://localhost:$REACT_PORT"
    echo "   Health:  http://localhost:$API_PORT/health"
    echo "  Press Ctrl+C to stop."
    wait
    ;;
  api)
    start_api
    echo ""
    ok "API server running on http://localhost:$API_PORT"
    echo "  Press Ctrl+C to stop."
    wait
    ;;
  react)
    start_react
    echo ""
    ok "React dev server running on http://localhost:$REACT_PORT"
    echo "  Press Ctrl+C to stop."
    wait
    ;;
esac