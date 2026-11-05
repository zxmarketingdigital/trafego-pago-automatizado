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

TOKEN = "EAA" + "SEGREDO123"  # montado em duas partes: é valor de teste, não credencial


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

    def test_json_aninhado_e_url_encoded_mascarados(self):
        _, log = self._rodar(
            "import json\nprint(json.dumps({'corpo': json.dumps({'access_token': '%s'})}))\n"
            "print('x?access_token%%3D%s&y=1')\n" % (TOKEN, TOKEN)
        )
        self.assertNotIn(TOKEN, log)

    def test_token_meta_sem_chave_ao_lado_e_mascarado(self):
        cru = "EAA" + "b1" * 20
        _, log = self._rodar("print('resposta', '%s')\n" % cru)
        self.assertNotIn(cru, log)
        self.assertIn("EAA***", log)

    def test_token_meta_colado_em_outro_texto_e_mascarado(self):
        cru = "EAA" + "b1" * 20
        _, log = self._rodar("print('u?input_token%%3D%s')\nprint('conta_%s')\nprint('conta%s')\n" % (cru, cru, cru))
        self.assertNotIn(cru, log)
        self.assertEqual(log.count("EAA***"), 3)

    def test_linha_sem_quebra_no_fim_chega_ao_log(self):
        _, log = self._rodar("import sys\nsys.stdout.write('ultima linha access_token=%s')\n" % TOKEN)
        self.assertIn("ultima linha access_token=***", log)
        self.assertNotIn(TOKEN, log)

    def test_falha_de_escrita_no_log_nao_derruba_a_coleta(self):
        rc, log = self._rodar(
            "import sys\n"
            "class Quebrado:\n"
            "    def write(self, t):\n        raise OSError('disco cheio')\n"
            "    def flush(self):\n        raise OSError('disco cheio')\n"
            "antes = sys.stdout._f\nsys.stdout._f = Quebrado()\n"
            "print('linha perdida')\nsys.stdout._f = antes\n"
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("linha perdida", log)
        self.assertIn("dashboard ok", log)

    def test_erro_com_log_quebrado_ainda_sai_com_codigo_1(self):
        rc, _ = self._rodar(
            "import sys\n"
            "class Quebrado:\n"
            "    def write(self, t):\n        raise OSError('disco cheio')\n"
            "    def flush(self):\n        raise OSError('disco cheio')\n"
            "sys.stdout._f = Quebrado()\nraise RuntimeError('falhou')\n"
        )
        self.assertEqual(rc, 1)

    def test_flush_grava_linha_sem_quebra_antes_de_matarem_a_tarefa(self):
        _, log = self._rodar(
            "import os\nprint('coletando conta 3 access_token=%s', end='', flush=True)\nos._exit(9)\n" % TOKEN
        )
        self.assertIn("coletando conta 3 access_token=***", log)
        self.assertNotIn(TOKEN, log)

    def test_flush_entre_chave_e_valor_nao_vaza(self):
        _, log = self._rodar("print('access_token=', end='', flush=True)\nprint('%s fim')\n" % TOKEN)
        self.assertNotIn(TOKEN, log)
        self.assertIn("access_token=*** fim", log)

    def test_flush_no_meio_do_valor_nao_vaza_o_resto(self):
        _, log = self._rodar("print('access_token=EAAS', end='', flush=True)\nprint('EGREDO123 fim')\n")
        self.assertNotIn("EGREDO123", log)
        self.assertIn("access_token=*** fim", log)

    def test_flush_no_meio_de_token_meta_sem_chave_nao_vaza(self):
        cru = "EAA" + "b1" * 20
        _, log = self._rodar("print('resposta %s', end='', flush=True)\nprint('%s')\n" % (cru[:10], cru[10:]))
        self.assertNotIn(cru[:10], log)
        self.assertNotIn(cru[10:], log)
        self.assertIn("resposta EAA***", log)

    def test_flush_nao_duplica_o_que_ja_foi_gravado(self):
        _, log = self._rodar("print('conta 1', end='', flush=True)\nprint(' ok', flush=True)\nprint('conta 2')\n")
        self.assertEqual(log.count("conta 1 ok\n"), 1)
        self.assertEqual(log.count("conta 2\n"), 1)

    def test_excecao_grava_traceback_mascarado(self):
        rc, log = self._rodar("def coletar():\n    raise KeyError('u?access_token=%s')\ncoletar()\n" % TOKEN)
        self.assertEqual(rc, 1)
        self.assertIn("Traceback", log)
        self.assertIn("coletar", log)
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
