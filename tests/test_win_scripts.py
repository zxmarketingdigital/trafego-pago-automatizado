"""Testes dos scripts do Agendador do Windows que rodam em qualquer sistema: máscara de
token no log do fetch e recusa de Host externo no server do dashboard."""
import functools
import http.client
import http.server
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import serve_dashboard_win  # noqa: E402

TOKEN = "EAASEGREDO123"


class TestLogDoFetch(unittest.TestCase):
    def _rodar(self, fetch_metrics):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        meta = tmp / "scripts" / "meta"
        meta.mkdir(parents=True)
        shutil.copy(REPO / "scripts" / "run_fetch_win.py", meta)
        (meta / "tpa_paths.py").write_text(
            "class P:\n    home = 'x'\n\ndef active_paths():\n    return P\n", encoding="utf-8"
        )
        (meta / "fetch_metrics.py").write_text(fetch_metrics, encoding="utf-8")
        (meta / "paid_traffic_dashboard.py").write_text("print('dashboard ok')\n", encoding="utf-8")
        res = subprocess.run([sys.executable, "-X", "utf8", str(meta / "run_fetch_win.py")], capture_output=True)
        return res.returncode, (tmp / "logs" / "fetch.log").read_text(encoding="utf-8")

    def test_systemexit_com_url_mascara_o_token(self):
        rc, log = self._rodar("import sys\nsys.exit('falha em https://g/x?access_token=%s&a=1')\n" % TOKEN)
        self.assertEqual(rc, 1)
        self.assertNotIn(TOKEN, log)
        self.assertIn("access_token=***", log)

    def test_print_e_excecao_mascaram_o_token(self):
        rc, log = self._rodar(
            "print('GET https://g/x?fb_exchange_token=%s')\nraise RuntimeError('u?client_secret=%s')\n" % (TOKEN, TOKEN)
        )
        self.assertEqual(rc, 1)
        self.assertNotIn(TOKEN, log)
        self.assertIn("fb_exchange_token=***", log)
        self.assertIn("client_secret=***", log)

    def test_valor_em_write_separado_e_mascarado(self):
        _, log = self._rodar("print('access_token=', '%s')\n" % TOKEN)
        self.assertNotIn(TOKEN, log)

    def test_formato_de_dict_e_json_mascarados(self):
        _, log = self._rodar(
            "print({'access_token': '%s'})\nprint('{\"client_secret\": \"%s\"}')\n" % (TOKEN, TOKEN)
        )
        self.assertNotIn(TOKEN, log)
        self.assertEqual(log.count("***"), 2)

    def test_linha_sem_quebra_no_fim_chega_ao_log(self):
        _, log = self._rodar("import sys\nsys.stdout.write('ultima linha access_token=%s')\n" % TOKEN)
        self.assertIn("ultima linha access_token=***", log)
        self.assertNotIn(TOKEN, log)

    def test_sucesso_roda_os_dois_scripts(self):
        rc, log = self._rodar("print('fetch ok')\n")
        self.assertEqual(rc, 0)
        self.assertIn("fetch ok", log)
        self.assertIn("dashboard ok", log)


class TestHostDoDashboard(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "a.html").write_text("dados", encoding="utf-8")
        handler = functools.partial(serve_dashboard_win.LocalOnlyHandler, directory=str(tmp))
        handler.log_message = lambda *a: None
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def _status(self, host):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("GET", "/a.html", skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
        res = conn.getresponse()
        res.read()
        conn.close()
        return res.status

    def test_host_local_responde(self):
        self.assertEqual(self._status("127.0.0.1:%d" % self.port), 200)
        self.assertEqual(self._status("localhost:%d" % self.port), 200)

    def test_host_externo_recebe_403(self):
        self.assertEqual(self._status("atacante.example:%d" % self.port), 403)


if __name__ == "__main__":
    unittest.main()
