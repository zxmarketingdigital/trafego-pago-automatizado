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


class LocalOnlyHandler(http.server.SimpleHTTPRequestHandler):
    """Só responde a Host local. Sem isso, uma página de terceiros que aponte o próprio
    domínio para 127.0.0.1 (DNS rebinding) lê os dados do dashboard no navegador do aluno."""

    def parse_request(self):
        if not super().parse_request():
            return False
        if (self.headers.get("Host") or "").split(":")[0].lower() not in ("127.0.0.1", "localhost"):
            self.send_error(403)
            return False
        return True


def main():
    # <projeto>/scripts/meta -> <projeto>/logs; aberto antes de tudo para nenhum erro sumir
    log_dir = HERE.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(log_dir / "dashboard-server.log", "a", encoding="utf-8", buffering=1)

    import tpa_paths

    p = tpa_paths.active_paths()
    dash = p.home / "dashboards"

    handler = functools.partial(LocalOnlyHandler, directory=str(dash))
    with http.server.ThreadingHTTPServer(("127.0.0.1", p.port), handler) as httpd:
        print(f"servindo {dash} em http://127.0.0.1:{p.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
