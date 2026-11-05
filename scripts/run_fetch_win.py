"""run_fetch_win.py — equivalente Windows do run_fetch.sh (Agendador de Tarefas).

Roda no projeto onde esta cópia mora (tpa_paths.py ao lado): coleta as métricas
(fetch_metrics.py) e regera o HTML do dashboard (paid_traffic_dashboard.py).
Pensado para rodar com `pythonw.exe -X utf8` (sem janela; sem -X utf8 os scripts
gravam os JSON/HTML em cp1252). A saída vai para logs/fetch.log.
"""
import datetime
import re
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# <projeto>/scripts/meta -> <projeto>/logs; aberto antes de tudo para nenhum erro sumir
log_dir = HERE.parent.parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log = open(log_dir / "fetch.log", "a", encoding="utf-8")
sys.stdout = sys.stderr = log

print(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] fetch", flush=True)
if not sys.flags.utf8_mode:
    print("⚠️  rodando sem -X utf8: arquivos podem sair em cp1252", flush=True)
try:
    import tpa_paths  # noqa: E402
    print(f"projeto: {tpa_paths.active_paths().home}", flush=True)
except Exception as e:  # noqa: BLE001
    print(f"❌ tpa_paths: {e!r}", flush=True)
    sys.exit(1)
rc = 0
for script in ("fetch_metrics.py", "paid_traffic_dashboard.py"):
    sys.argv = [str(HERE / script)]
    try:
        runpy.run_path(str(HERE / script), run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            print(f"❌ {script} saiu com código {e.code}", flush=True)
            rc = 1
            break
    except Exception as e:  # noqa: BLE001
        # erro de rede traz a URL no repr, e a URL da Graph API traz o token
        msg = re.sub(r"(access_token|fb_exchange_token|client_secret)=[^&\s'\"]+", r"\1=***", repr(e))
        print(f"❌ {script}: {msg}", flush=True)
        rc = 1
        break
log.flush()
sys.exit(rc)
