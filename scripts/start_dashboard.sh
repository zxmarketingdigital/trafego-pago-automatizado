#!/bin/bash
# start_dashboard.sh — sobe http server na pasta de dashboards (idempotente)
# Roda no PROJETO onde esta copia mora (ver tpa_paths.py): o dashboard de cada
# cliente tem pasta e porta proprias. Sem projeto nomeado = ~/.operacao-ia e 8888.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON_BIN:-python3}"
if [ -f "$HERE/tpa_paths.py" ]; then
  OPERACAO="$("$PY" "$HERE/tpa_paths.py" --home)"
  # a porta é do projeto: um PORT herdado do ambiente não pode mandar este
  # dashboard para a porta de outro projeto
  PORT="$("$PY" "$HERE/tpa_paths.py" --port)"
else
case "$HERE" in
    */tpa-projetos/*)
        echo "❌ tpa_paths.py não está em $HERE: esta cópia pertence a um projeto e não pode cair no projeto padrão. Rode o setup do projeto de novo (setup_metrics_fetcher.py / setup_dashboard.py)." >&2
        exit 1
        ;;
esac
  OPERACAO="${OPERACAO_IA_HOME:-$HOME/.operacao-ia}"
  PORT="${PORT:-8888}"
fi

DASH_DIR="${OPERACAO}/dashboards"
LOG="${OPERACAO}/logs/dashboard-server.log"

mkdir -p "$(dirname "$LOG")" "$DASH_DIR"

# Reinicia o server anterior DESTE projeto, se estiver escutando na porta dele.
# Só quem está em LISTEN (nunca navegador com a aba aberta) e só se for http.server.
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -nP -iTCP:${PORT} -sTCP:LISTEN -t 2>/dev/null || true)"
else
  PIDS=""
  echo "Aviso: lsof não está instalado; não consigo reiniciar um server antigo na porta ${PORT}. Se ela estiver ocupada, o novo falha (veja o log)." >&2
fi
for PID in $PIDS; do
  if ps -o command= -p "$PID" 2>/dev/null | grep -q "http.server"; then
    echo "Server já rodando em :${PORT}, reiniciando..."
    kill "$PID" 2>/dev/null || true
    sleep 1
  else
    echo "Porta ${PORT} ocupada por outro programa (pid ${PID}); não vou mexer nele." >&2
    exit 1
  fi
done

cd "$DASH_DIR"
echo "[$(date)] start http server on :${PORT} (${OPERACAO})" >> "$LOG"
exec python3 -m http.server "$PORT" --bind 127.0.0.1 >> "$LOG" 2>&1
