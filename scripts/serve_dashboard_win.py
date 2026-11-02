"""serve_dashboard_win.py — equivalente Windows do start_dashboard.sh (Agendador de Tarefas).

Serve <projeto>/dashboards na porta do projeto (tpa_paths.py ao lado), só em 127.0.0.1.
Roda com pythonw.exe (sem janela): stdout/stderr vão para logs/dashboard-server.log,
senão o http.server falha ao registrar cada acesso.
"""
import functools
import http.server
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# <projeto>/scripts/meta -> <projeto>/logs; aberto antes de tudo para nenhum erro sumir
log_dir = HERE.parent.parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
sys.stdout = sys.stderr = open(log_dir / "dashboard-server.log", "a", encoding="utf-8", buffering=1)

import tpa_paths  # noqa: E402

p = tpa_paths.active_paths()
dash = p.home / "dashboards"

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dash))
with http.server.ThreadingHTTPServer(("127.0.0.1", p.port), handler) as httpd:
    print(f"servindo {dash} em http://127.0.0.1:{p.port}")
    httpd.serve_forever()
