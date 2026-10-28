#!/usr/bin/env bash
# OM Search Engine - Unix Launcher (Backend + Frontend)

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "================================================================================"
echo "                     OM SEARCH ENGINE — APPLICATION LAUNCHER"
echo "================================================================================"
echo ""

if [ ! -f ".venv/bin/python" ]; then
    echo "[!] Virtual environment not found. Running setup first..."
    bash setup.sh
fi

echo "[1/2] Starting FastAPI Backend on http://127.0.0.1:8000 ..."
(cd backend && ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
BACKEND_PID=$!

echo "[2/2] Starting Vite Frontend on http://127.0.0.1:5173 ..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

cleanup() {
    echo ""
    echo "Stopping OM Search servers..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    echo "Servers stopped. Goodbye!"
    exit 0
}

trap cleanup SIGINT SIGTERM

echo ""
echo "================================================================================"
echo "[✓] OM Search is now running!"
echo "    - Frontend UI:  http://127.0.0.1:5173"
echo "    - Backend API: http://127.0.0.1:8000/docs"
echo "Press Ctrl+C to terminate both servers."
echo "================================================================================"
echo ""

# Try opening default browser
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:5173" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:5173" >/dev/null 2>&1 || true
fi

wait
