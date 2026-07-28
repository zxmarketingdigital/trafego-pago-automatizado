#!/usr/bin/env bash
# run_fetch.sh — wrapper pro LaunchAgent meta-fetch.
# Carrega meta.env (META_ACCESS_TOKEN, META_AD_ACCOUNT_ID) e roda fetch_metrics.py.
# Usado por com.zxlab.meta-fetch.plist.

set -e

META_ENV="$HOME/.operacao-ia/config/meta.env"
FETCH_PY="$HOME/.operacao-ia/scripts/meta/fetch_metrics.py"

if [ -f "$META_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$META_ENV"
    set +a
fi

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
exec "$PYTHON_BIN" "$FETCH_PY" "$@"
