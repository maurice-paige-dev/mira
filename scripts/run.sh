#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Start the Shipping Cost Advisor Chatbot
# ─────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/run.sh                      # Start API + React frontend
#   ./scripts/run.sh --api-only           # Start only the RAG API
#   ./scripts/run.sh --catalog            # Start the catalog & quoting API
#   ./scripts/run.sh --all                # Start everything
# ─────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

API_PORT="${API_PORT:-8000}"
CATALOG_PORT="${CATALOG_PORT:-8001}"
REACT_PORT="${REACT_PORT:-5173}"

info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; }
ok()    { echo -e "\033[1;32m[OK]\033[0m $*"; }

VENV_DIR="$SCRIPT_DIR/.venv"

check_prereqs() {
  info "Checking prerequisites\u2026"

  if ! command -v python3 &>/dev/null; then
    error "python3 is required but not found."
    exit 1
  fi

  if ! command -v node &>/dev/null; then
    error "node is required but not found."
    exit 1
  fi

  if [ ! -f "$VENV_DIR/bin/activate" ]; then
    info "No .venv found. Creating one\u2026"
    python3 -m venv "$VENV_DIR"
  fi

  if [ ! -d "$SCRIPT_DIR/frontend/chatbot/node_modules" ]; then
    info "Installing React frontend dependencies\u2026"
    cd "$SCRIPT_DIR/frontend/chatbot" && npm install
    cd "$SCRIPT_DIR"
  fi

  if [ ! -d "$SCRIPT_DIR/data/chroma_shipping_db" ]; then
    info "ChromaDB not found. Running RAG pipeline to build it\u2026"
    source "$VENV_DIR/bin/activate"
    pip install -q sentence-transformers chromadb pandas
    python -m backend.vector_store --no-interactive 2>&1 || true
    ok "ChromaDB should be built now."
  fi

  ok "All prerequisites satisfied."
}

start_api() {
  info "Starting RAG API server on port $API_PORT\u2026"
  source "$VENV_DIR/bin/activate"
  cd "$SCRIPT_DIR"
  pip install -q fastapi uvicorn sentence-transformers chromadb pandas 2>/dev/null || true
  uvicorn backend.api_rag:app --host 0.0.0.0 --port "$API_PORT" --reload &
  API_PID=$!
  ok "RAG API server started (PID: $API_PID)"
  echo "$API_PID" > /tmp/rag_api.pid
}

start_catalog() {
  info "Starting Catalog & Quoting API on port $CATALOG_PORT\u2026"
  source "$VENV_DIR/bin/activate"
  cd "$SCRIPT_DIR"
  pip install -q fastapi uvicorn pandas 2>/dev/null || true
  uvicorn backend.api_catalog:app --host 0.0.0.0 --port "$CATALOG_PORT" --reload &
  CAT_PID=$!
  ok "Catalog API server started (PID: $CAT_PID)"
  echo "$CAT_PID" > /tmp/catalog_api.pid
}

start_react() {
  info "Starting React dev server on port $REACT_PORT\u2026"
  cd "$SCRIPT_DIR/frontend/chatbot"
  npx vite --port "$REACT_PORT" --host &
  REACT_PID=$!
  ok "React dev server started (PID: $REACT_PID)"
  echo "$REACT_PID" > /tmp/chatbot_react.pid
}

cleanup() {
  echo ""
  info "Shutting down\u2026"
  for pidfile in /tmp/rag_api.pid /tmp/catalog_api.pid /tmp/chatbot_react.pid; do
    if [ -f "$pidfile" ]; then
      kill "$(cat "$pidfile")" 2>/dev/null || true
      rm -f "$pidfile"
    fi
  done
  ok "Stopped."
}

trap cleanup EXIT INT TERM

MODE="rag"
for arg in "$@"; do
  case "$arg" in
    --api-only|--rag) MODE="rag" ;;
    --catalog) MODE="catalog" ;;
    --react-only) MODE="react" ;;
    --all) MODE="all" ;;
    --help)
      echo "Usage: $0 [--rag | --catalog | --react-only | --all]"
      echo ""
      echo "  --rag          Start RAG chatbot API only (default)"
      echo "  --catalog      Start catalog & quoting API"
      echo "  --react-only   Start React frontend only"
      echo "  --all          Start RAG API, catalog API, and React frontend"
      exit 0
      ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Ecommerce Data Platform - Launcher                ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

check_prereqs

case "$MODE" in
  rag)
    start_api
    echo ""
    ok "RAG API server running on http://localhost:$API_PORT"
    echo "  Health:  http://localhost:$API_PORT/health"
    echo "  Press Ctrl+C to stop."
    wait
    ;;
  catalog)
    start_catalog
    echo ""
    ok "Catalog API server running on http://localhost:$CATALOG_PORT"
    echo "  Frontend: http://localhost:$CATALOG_PORT/"
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
  all)
    start_api
    start_catalog
    sleep 2
    start_react
    echo ""
    ok "All servers are running!"
    echo "   RAG API:     http://localhost:$API_PORT"
    echo "   Catalog API: http://localhost:$CATALOG_PORT"
    echo "   React:       http://localhost:$REACT_PORT"
    echo "  Press Ctrl+C to stop."
    wait
    ;;
esac
