"""Regressão: o setup instala SOZINHO, sem exigir nenhum setup anterior.

Este produto é vendido avulso. Versões antigas reprovavam a auditoria (E10, exit 1)
com "Pré-requisito Setup 5" e a finalização abortava sem config.json — o comprador
avulso não tem o Setup 5 e nunca terá. Se alguém reintroduzir esse acoplamento,
este teste fica vermelho.

Cada caso roda os scripts reais em subprocesso, com HOME temporário e sem rede:
nada toca o HOME real, o launchctl ou o browser (BROWSER=true).

    python3 tests/test_instala_sozinho.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / "setup"


class _HomeTemporario(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="tpa-avulso-"))
        self.config = self.home / ".operacao-ia" / "config" / "config.json"

    def tearDown(self):
        shutil.rmtree(str(self.home), ignore_errors=True)

    def env(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPERACAO_IA_HOME", "TPA_PROJECT")}
        env.update({"HOME": str(self.home), "USERPROFILE": str(self.home),
                    "BROWSER": "true", "PYTHONIOENCODING": "utf-8"})
        return env

    def run_py(self, code_or_script, *args):
        if code_or_script.endswith(".py"):
            cmd = [sys.executable, str(SETUP / code_or_script)] + list(args)
        else:
            cmd = [sys.executable, "-c", code_or_script]
        return subprocess.run(cmd, env=self.env(), cwd=str(REPO), capture_output=True,
                              text=True, encoding="utf-8", timeout=120)

    def write_config(self, text):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(text, encoding="utf-8")

    def read_config(self):
        return json.loads(self.config.read_text(encoding="utf-8"))

    def write_perfil(self):
        perfil = self.home / ".operacao-ia" / "config" / "meta_perfil.json"
        perfil.parent.mkdir(parents=True, exist_ok=True)
        perfil.write_text(json.dumps({"currency": "BRL", "kpis": [
            {"key": "cpa", "label": "CPA", "target": 30, "format": "currency"}]}),
            encoding="utf-8")


class EtapaZero(_HomeTemporario):
    def test_sem_config_cria_minimo_e_segue(self):
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Setup 5", r.stdout)
        self.assertEqual(self.read_config().get("phase_completed"), 0)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_config_corrompido_vira_backup_e_e_recriado(self):
        self.write_config("{isto nao e json")
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        backups = list(self.config.parent.glob("config.json.bak-*"))
        self.assertEqual(len(backups), 1, "corrompido tem que virar backup antes de recriar")
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{isto nao e json")
        self.assertEqual(self.read_config().get("phase_completed"), 0)

    def test_instalacao_anterior_e_aproveitada_sem_alterar(self):
        original = json.dumps({"phase_completed": 5, "nome": "aluno"}, indent=2)
        self.write_config(original)
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)


class Auditoria(_HomeTemporario):
    CODE = ("import sys; sys.path.insert(0, 'setup'); import setup_audit as a; "
            "ok, msg = a.c_phase_completed(); print(ok, msg); sys.exit(0 if ok else 3)")

    def test_sem_config_nao_reprova(self):
        r = self.run_py(self.CODE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_fase_zero_nao_reprova(self):
        self.write_config('{"phase_completed": 0}')
        r = self.run_py(self.CODE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_nenhum_check_cita_setup_anterior(self):
        texto = (SETUP / "setup_audit.py").read_text(encoding="utf-8")
        self.assertNotIn("Pré-requisito Setup 5", texto)


class FinalizacaoEUninstall(_HomeTemporario):
    REVERT = ("import sys; sys.path.insert(0, 'setup'); import setup_uninstall as u; "
              "u.revert_phase()")

    def test_avulso_vai_a_6_e_uninstall_volta_a_0(self):
        self.write_perfil()
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cfg = self.read_config()
        self.assertEqual(cfg["phase_completed"], 6)
        self.assertEqual(cfg["setup6"]["phase_before"], 0)
        r = self.run_py(self.REVERT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 0,
                         "uninstall de comprador avulso não pode inventar um Setup 5")

    def test_fase_maior_nunca_regride(self):
        self.write_perfil()
        self.write_config('{"phase_completed": 9}')
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 9)

    def test_instalacao_antiga_sem_registro_volta_a_5(self):
        self.write_config('{"phase_completed": 6}')
        r = self.run_py(self.REVERT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 5)


class FaseNaoSePerde(_HomeTemporario):
    """Passada 1 do review: config corrompido, registro antigo e gravacao travada no Windows."""

    def test_corrompido_mantem_fase_e_uninstall_volta_a_ela(self):
        self.write_perfil()
        self.write_config('{"phase_completed": 5, "nome": "aluno",}')  # virgula sobrando
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 5,
                         "recriar config corrompido nao pode zerar a fase do aluno")
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["setup6"]["phase_before"], 5)
        r = self.run_py(FinalizacaoEUninstall.REVERT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 5)

    def test_finalizacao_com_corrompido_mantem_fase_textual(self):
        self.write_perfil()
        self.write_config('{"phase_completed": "week5" oops')
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cfg = self.read_config()
        self.assertEqual(cfg["phase_completed"], 6)
        self.assertEqual(cfg["setup6"]["phase_before"], "week5")

    def test_registro_antigo_e_regravado(self):
        self.write_perfil()
        self.write_config(json.dumps({"phase_completed": 5, "setup6": {"phase_before": 3}}))
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["setup6"]["phase_before"], 5)

    def test_replace_travado_tenta_de_novo(self):
        code = ("import sys, os; sys.path.insert(0, 'setup'); from unittest import mock; "
                "import setup_base_s6 as b; b.REPLACE_ESPERA_S = 0; real = os.replace; n = [0]\n"
                "def flaky(a, d):\n"
                "    n[0] += 1\n"
                "    if n[0] < 3: raise PermissionError('em uso')\n"
                "    return real(a, d)\n"
                "os.makedirs(os.path.dirname(str(b.CONFIG)), exist_ok=True)\n"
                "with mock.patch('os.replace', flaky): b.write_config_atomic({'phase_completed': 2}, b.CONFIG)\n"
                "print(n[0])")
        r = self.run_py(code)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), "3")
        self.assertEqual(self.read_config()["phase_completed"], 2)

    def test_replace_sempre_travado_sai_1_sem_traceback(self):
        self.write_perfil()
        self.write_config('{"phase_completed": 0}')
        code = ("import sys; sys.path.insert(0, 'setup'); from unittest import mock; "
                "import setup_base_s6 as b; b.REPLACE_ESPERA_S = 0; import setup_final_s6 as f\n"
                "with mock.patch('os.replace', side_effect=PermissionError('em uso')): f.main()")
        r = self.run_py(code)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("A fase NÃO foi atualizada", r.stdout)
        self.assertEqual(self.read_config()["phase_completed"], 0)
        self.assertEqual(list(self.config.parent.glob("config.json.tmp-*")), [],
                         "temporario nao pode sobrar")

    def test_fase_null_volta_a_0_nunca_inventa_5(self):
        self.write_perfil()
        self.write_config('{"phase_completed": null}')
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_py(FinalizacaoEUninstall.REVERT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 0)

    def test_perfil_invalido_nao_mexe_na_fase(self):
        perfil = self.home / ".operacao-ia" / "config" / "meta_perfil.json"
        perfil.parent.mkdir(parents=True, exist_ok=True)
        perfil.write_text('{"currency": "BRL"}', encoding="utf-8")
        self.write_config('{"phase_completed": 2}')
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 2)

    def test_corrompido_com_fase_textual_longa(self):
        fase = "semana 5 concluida pelo aluno em 12/03/2026 com todos os KPIs do painel"
        self.write_config('{"phase_completed": "%s",,' % fase)
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], fase)

    def test_corrompido_mantem_registro_do_uninstall(self):
        self.write_config('{"phase_completed": 6, "setup6": {"phase_before": 2},}')
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["setup6"]["phase_before"], 2)
        r = self.run_py(FinalizacaoEUninstall.REVERT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 2)

    def test_leitura_bloqueada_nao_vira_corrupcao(self):
        original = '{"phase_completed": 4, "outro_projeto": {"x": 1}}'
        self.write_config(original)
        code = ("import sys; sys.path.insert(0, 'setup'); from unittest import mock; "
                "import setup_base_s6 as b\n"
                "with mock.patch.object(b.tpa_paths, 'read_text_compat', side_effect=PermissionError('em uso')):\n"
                "    sys.exit(0 if b.check_config() is False else 3)")
        r = self.run_py(code)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        self.assertEqual(list(self.config.parent.glob("config.json.bak-*")), [])

    def test_bak_travado_nao_zera_fase(self):
        self.write_config('{"phase_completed": 5,}')
        code = ("import sys; sys.path.insert(0, 'setup'); from unittest import mock; "
                "import setup_base_s6 as b, pathlib; real = pathlib.Path.read_bytes\n"
                "def trava_bak(self):\n"
                "    if '.bak-' in self.name: raise PermissionError('bak em uso')\n"
                "    return real(self)\n"
                "with mock.patch('pathlib.Path.read_bytes', trava_bak):\n"
                "    sys.exit(0 if b.check_config() else 3)")
        r = self.run_py(code)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 5)

    def test_fase_lista_registra_a_fase_lida(self):
        self.write_perfil()
        self.write_config('{"phase_completed": [5]}')
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["setup6"]["phase_before"], 5)

    def test_uninstall_leitura_bloqueada_nao_e_json_invalido(self):
        self.write_config('{"phase_completed": 6}')
        code = ("import sys; sys.path.insert(0, 'setup'); from unittest import mock; "
                "import setup_uninstall as u\n"
                "with mock.patch.object(u.tpa_paths, 'read_text_compat', side_effect=PermissionError('em uso')):\n"
                "    u.revert_phase()\n"
                "print('|'.join(u.PENDENCIAS))")
        r = self.run_py(code)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("arquivo em uso", r.stdout)
        self.assertNotIn("JSON inválido", r.stdout)

    def test_fase_textual_com_escape_e_desescapada(self):
        self.write_config('{"phase_completed": "conclu\\u00edda na semana 5", "x": 1')
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], "concluída na semana 5")

    def test_fase_em_expoente_nao_regride(self):
        self.write_config('{"phase_completed": 1e1, "x": 1')
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 10)

    def test_fase_textual_com_aspas_escapadas(self):
        self.write_config('{"phase_completed": "semana \\"5\\" ok", "x": 1')
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 'semana "5" ok')

    def test_surrogate_solto_nao_trava_finalizacao(self):
        self.write_config('{"phase_completed": 5, "origem": "x\\ud83d"}')
        self.write_perfil()
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 6)

    def test_virgula_sobrando_preserva_outros_projetos(self):
        self.write_config('{"phase_completed": 5, "projeto_b": {"token_path": "/x"},}')
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cfg = self.read_config()
        self.assertEqual(cfg["projeto_b"], {"token_path": "/x"})
        self.assertEqual(cfg["phase_completed"], 5)
        self.assertTrue(list(self.config.parent.glob("config.json.bak-*")))

    def test_virgula_dentro_de_string_nao_e_alterada(self):
        self.write_config('{"nota": "a ,} b", "phase_completed": 5,}')
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["nota"], "a ,} b")

    def test_fase_ilegivel_preserva_registro_do_uninstall(self):
        longa = "x" * 600
        self.write_config('{"setup6": {"phase_before": 3}, "phase_completed": "%s"' % longa)
        self.write_perfil()
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cfg = self.read_config()
        self.assertEqual(cfg["phase_completed"], 6)
        self.assertEqual(cfg["setup6"]["phase_before"], 3)

    def test_fase_zero_legitima_sobrescreve_registro(self):
        self.write_config('{"phase_completed": 0, "setup6": {"phase_before": 3},}')
        self.write_perfil()
        r = self.run_py("setup_final_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cfg = self.read_config()
        self.assertEqual(cfg["phase_completed"], 6)
        self.assertEqual(cfg["setup6"]["phase_before"], 0)

    def test_bom_e_byte_invalido_nao_derrubam_o_reparo(self):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(b'\xef\xbb\xbf{"phase_completed": 5, "projeto_b": 1,}')
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["projeto_b"], 1)
        self.config.write_bytes(b'{"phase_completed": 5, "nome": "caf\x81\xe9"')
        r = self.run_py("setup_base_s6.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read_config()["phase_completed"], 5)

    def test_uninstall_grava_atomico(self):
        texto = (SETUP / "setup_uninstall.py").read_text(encoding="utf-8")
        self.assertNotIn("CONFIG.write_text", texto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
