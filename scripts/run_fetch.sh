#!/usr/bin/env bash
# run_fetch.sh — wrapper pro LaunchAgent meta-fetch.
# Carrega meta.env (META_ACCESS_TOKEN, META_AD_ACCOUNT_ID) e roda fetch_metrics.py.
# Usado por com.zxlab.meta-fetch.plist. Roda no PROJETO onde esta copia mora
# (ver tpa_paths.py); sem projeto nomeado = ~/.operacao-ia, como sempre foi.

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
if [ -f "$HERE/tpa_paths.py" ]; then
    OPERACAO="$("$PYTHON_BIN" "$HERE/tpa_paths.py" --home)"
else
    case "$HERE" in
        */tpa-projetos/*)
            echo "❌ tpa_paths.py não está em $HERE: esta cópia pertence a um projeto e não pode cair no projeto padrão. Rode o setup do projeto de novo (setup_metrics_fetcher.py / setup_dashboard.py)." >&2
            exit 1
            ;;
    esac
    OPERACAO="${OPERACAO_IA_HOME:-$HOME/.operacao-ia}"
fi

META_ENV="$OPERACAO/config/meta.env"
FETCH_PY="$HERE/fetch_metrics.py"

if [ -f "$META_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$META_ENV"
    set +a
fi

exec "$PYTHON_BIN" "$FETCH_PY" "$@"
