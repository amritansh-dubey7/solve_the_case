#!/usr/bin/env bash
# One-click start for "Solve the Case" — backend (FastAPI) + frontend (Vite).
# Usage:  ./start.sh
# Stop everything with Ctrl+C (both processes are cleaned up on exit).

set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

echo "==> Solve the Case — starting backend + frontend"

# ---------- Backend ----------
cd "$BACKEND_DIR"

if [ ! -d "venv" ]; then
  echo "==> Creating backend virtualenv..."
  python3 -m venv venv
fi
source venv/bin/activate

echo "==> Installing backend dependencies (first run downloads PyTorch for"
echo "    sentence-transformers — can take 3-10+ min depending on your connection;"
echo "    this is NOT stuck, just slow. Later runs are near-instant)."
pip install -r requirements.txt

if [ ! -f ".env" ]; then
  echo "==> No backend/.env found. Creating one — pick a provider and add its key."
  cat > .env << 'EOF'
# Choose ONE provider: anthropic (paid) or groq (free tier, no card needed)
LLM_PROVIDER=groq

# Fill in whichever key matches LLM_PROVIDER above.
ANTHROPIC_API_KEY=
GROQ_API_KEY=
EOF
  echo "    (edit backend/.env — set LLM_PROVIDER and the matching key — then re-run this script)"
fi

echo "==> Starting backend on http://localhost:8000 ..."
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# Give the backend a moment to come up, then run ingestion once if needed.
sleep 2
if [ ! -f "$ROOT_DIR/corpus/case_001/graph.json" ] || [ ! -s "$ROOT_DIR/corpus/case_001/graph.json" ]; then
  echo "==> Running initial ingestion (POST /ingest)..."
  curl -s -X POST http://localhost:8000/ingest > /dev/null || echo "    (ingestion call failed — you can retry manually later)"
fi

# ---------- Frontend ----------
cd "$FRONTEND_DIR"

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

if [ ! -d "node_modules" ]; then
  echo "==> Installing frontend dependencies..."
  npm install
fi

echo "==> Starting frontend on http://localhost:5173 ..."
npm run dev &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "==> Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "=================================================="
echo " Backend:  http://localhost:8000  (docs at /docs)"
echo " Frontend: http://localhost:5173"
echo " Press Ctrl+C to stop both."
echo "=================================================="

wait
