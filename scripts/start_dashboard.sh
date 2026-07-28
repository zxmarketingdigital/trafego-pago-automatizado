#!/bin/bash
# start_dashboard.sh — sobe http server na pasta de dashboards (idempotente)
set -euo pipefail

DASH_DIR="${HOME}/.operacao-ia/dashboards"
PORT="${PORT:-8888}"
LOG="${HOME}/.operacao-ia/logs/dashboard-server.log"

mkdir -p "$(dirname "$LOG")" "$DASH_DIR"

# Mata server anterior se já estiver rodando
if lsof -ti tcp:${PORT} >/dev/null 2>&1; then
  echo "Server já rodando em :${PORT}, reiniciando..."
  lsof -ti tcp:${PORT} | xargs kill -9 2>/dev/null || true
  sleep 1
fi

cd "$DASH_DIR"
echo "[$(date)] start http server on :${PORT}" >> "$LOG"
exec python3 -m http.server "$PORT" --bind 127.0.0.1 >> "$LOG" 2>&1
