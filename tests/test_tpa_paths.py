"""Testes do helper tpa_paths: pastas por projeto, retrocompatibilidade e isolamento.

Sem rede, sem launchctl, sem tocar no HOME real: tudo em diretórios temporários.
"""
import json
import os
import plistlib
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import tpa_paths  # noqa: E402


def _clean_env(home, **extra):
    env = {"HOME": str(home)}
    env.update(extra)
    return env


class DefaultProjectIsLegacyTest(unittest.TestCase):
    """O projeto padrão tem que ser EXATAMENTE o layout de sempre (git pull não quebra ninguém)."""

    def test_default_paths_match_the_old_hardcoded_layout(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, _clean_env(tmp), clear=True):
            p = tpa_paths.resolve()
            legacy = Path.home() / ".operacao-ia"
            self.assertEqual(p.name, "default")
            self.assertEqual(p.home, legacy)
            self.assertEqual(p.meta_env, legacy / "config" / "meta.env")
            self.assertEqual(p.perfil, legacy / "config" / "meta_perfil.json")
            self.assertEqual(p.progress, legacy / "config" / "setup6_progress.json")
            self.assertEqual(p.shared_config, legacy / "config" / "config.json")
            self.assertEqual(p.scripts_meta, legacy / "scripts" / "meta")
            self.assertEqual(p.dashboards, legacy / "dashboards")
            self.assertEqual(p.logs, legacy / "logs")
            self.assertEqual(p.briefings, legacy / "briefings")
            self.assertEqual(p.leads, legacy / "leads")
            self.assertEqual(p.port, 8888)

    def test_default_labels_keep_the_historic_names(self):
        self.assertEqual(tpa_paths.label_for("com.zxlab.meta-fetch", "default"), "com.zxlab.meta-fetch")
        self.assertEqual(
            tpa_paths.label_for("com.zxlab.meta-fetch", "cliente-a"), "com.zxlab.meta-fetch.cliente-a"
        )

    def test_operacao_ia_home_env_moves_the_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _clean_env(tmp, OPERACAO_IA_HOME=str(Path(tmp) / "outra"))
            with patch.dict(os.environ, env, clear=True):
                p = tpa_paths.resolve()
                self.assertEqual(p.home, Path(tmp) / "outra")
                self.assertEqual(p.meta_env, Path(tmp) / "outra" / "config" / "meta.env")

    def test_creating_a_named_project_does_not_touch_default_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / ".operacao-ia"
            (base / "config").mkdir(parents=True)
            (base / "config" / "meta.env").write_text("META_AD_ACCOUNT_ID=act_1\n")
            (base / "dashboards").mkdir()
            (base / "dashboards" / "paid-traffic-7d.json").write_text("{}")
            before = {
                f.relative_to(base): f.read_bytes() for f in base.rglob("*") if f.is_file()
            }
            tpa_paths.create_project("cliente-a", base)
            after = {
                f.relative_to(base): f.read_bytes()
                for f in base.rglob("*")
                if f.is_file() and tpa_paths.PROJECTS_SUBDIR not in f.relative_to(base).parts
            }
            self.assertEqual(before, after)


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.base = self.tmp / ".operacao-ia"
        self.env = _clean_env(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pointer_selects_the_active_project(self):
        tpa_paths.create_project("cliente-a", self.base)  # ativa
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(tpa_paths.resolve().name, "cliente-a")
            tpa_paths.set_active("default", self.base)
            self.assertEqual(tpa_paths.resolve().name, "default")

    def test_env_var_beats_pointer(self):
        tpa_paths.create_project("cliente-a", self.base)
        tpa_paths.create_project("cliente-b", self.base)  # ponteiro = b
        with patch.dict(os.environ, dict(self.env, TPA_PROJECT="cliente-a"), clear=True):
            self.assertEqual(tpa_paths.resolve().name, "cliente-a")
        with patch.dict(os.environ, dict(self.env, TPA_PROJECT="default"), clear=True):
            self.assertEqual(tpa_paths.resolve().name, "default")

    def test_unknown_project_fails_closed_never_falls_back_to_default(self):
        with patch.dict(os.environ, dict(self.env, TPA_PROJECT="fantasma"), clear=True):
            with self.assertRaises(tpa_paths.TpaError):
                tpa_paths.resolve()
        (self.base / "tpa-projetos").mkdir(parents=True)
        (self.base / "tpa-projetos" / "ativo").write_text("sumiu\n")  # ponteiro pendente
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(tpa_paths.TpaError):
                tpa_paths.resolve()

    def test_active_paths_exits_with_message_on_error(self):
        with patch.dict(os.environ, dict(self.env, TPA_PROJECT="fantasma"), clear=True):
            with self.assertRaises(SystemExit) as ctx:
                tpa_paths.active_paths()
            self.assertIn("fantasma", str(ctx.exception))

    def test_installed_copy_resolves_by_its_own_location(self):
        """Agendamento (LaunchAgent/cron) roda a cópia instalada: o projeto vem do lugar dela."""
        tpa_paths.create_project("cliente-a", self.base)
        tpa_paths.create_project("cliente-b", self.base)  # ponteiro = b
        meta_a = self.base / "tpa-projetos" / "cliente-a" / "scripts" / "meta"
        dst = tpa_paths.sync_helper(meta_a)
        with patch.dict(os.environ, dict(self.env, TPA_PROJECT="cliente-b"), clear=True):
            p = tpa_paths.resolve(file=str(dst))
        self.assertEqual(p.name, "cliente-a")
        self.assertEqual(p.home, self.base / "tpa-projetos" / "cliente-a")
        self.assertEqual(p.base, self.base)

    def test_installed_copy_in_legacy_folder_is_default(self):
        meta = self.base / "scripts" / "meta"
        dst = tpa_paths.sync_helper(meta)
        with patch.dict(os.environ, dict(self.env, TPA_PROJECT="qualquer"), clear=True):
            p = tpa_paths.resolve(file=str(dst))
        self.assertEqual((p.name, p.home), ("default", self.base))

    def test_repo_checkout_is_not_mistaken_for_an_installed_copy(self):
        self.assertIsNone(tpa_paths.installed_location(str(REPO / "scripts" / "tpa_paths.py")))


class NamesAndPortsTest(unittest.TestCase):
    def test_invalid_names_are_rejected(self):
        for bad in ("", "Cliente", "../fora", "a/b", "a b", "-x", "x" * 41, ".oculto", None):
            with self.assertRaises(tpa_paths.TpaError, msg=repr(bad)):
                tpa_paths.validate_name(bad)

    def test_reserved_names_cannot_be_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("default", "ativo"):
                with self.assertRaises(tpa_paths.TpaError):
                    tpa_paths.create_project(name, Path(tmp))

    def test_duplicate_project_is_refused_without_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tpa_paths.create_project("cliente-a", base)
            marker = base / "tpa-projetos" / "cliente-a" / "config" / "meta.env"
            marker.write_text("META_AD_ACCOUNT_ID=act_7\n")
            with self.assertRaises(tpa_paths.TpaError):
                tpa_paths.create_project("cliente-a", base)
            self.assertEqual(marker.read_text(), "META_AD_ACCOUNT_ID=act_7\n")

    def test_each_project_gets_its_own_port_and_skips_busy_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            busy = {8890}
            free = lambda port: port not in busy  # noqa: E731
            a = tpa_paths.create_project("a", base, port_free=free)
            b = tpa_paths.create_project("b", base, port_free=free)
            c = tpa_paths.create_project("c", base, port_free=free)
            self.assertEqual([a.port, b.port, c.port], [8889, 8891, 8892])
            self.assertEqual(tpa_paths.Paths("default", base).port, 8888)

    def test_real_port_probe_detects_a_listening_socket(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        try:
            self.assertFalse(tpa_paths._port_is_free(sock.getsockname()[1]))
        finally:
            sock.close()

    def test_named_project_without_valid_port_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            p = tpa_paths.create_project("a", base)
            p.project_file.write_text(json.dumps({"nome": "a"}))
            with self.assertRaises(tpa_paths.TpaError):
                tpa_paths.Paths("a", base).port


class SchedulingTest(unittest.TestCase):
    def _render_all(self, p, python="/usr/bin/python3"):
        out = {}
        for template in sorted((REPO / "launchagents").glob("com.zxlab.meta-*.plist")):
            base_label = template.name[: -len(".plist")]
            text = tpa_paths.render_plist(template.read_text(), p, base_label, python)
            self.assertNotIn("{", text, template.name)  # nenhum placeholder sobrando
            out[base_label] = plistlib.loads(text.encode())
        return out

    def test_default_plists_match_the_old_install(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, _clean_env(tmp), clear=True):
            p = tpa_paths.resolve()
            plists = self._render_all(p)
            legacy = str(Path.home() / ".operacao-ia")
            fetch = plists["com.zxlab.meta-fetch"]
            self.assertEqual(fetch["Label"], "com.zxlab.meta-fetch")
            self.assertEqual(fetch["ProgramArguments"], ["/bin/bash", legacy + "/scripts/meta/run_fetch.sh"])
            self.assertEqual(fetch["StandardOutPath"], legacy + "/logs/meta-fetch.stdout.log")
            dash = plists["com.zxlab.meta-dashboard-server"]
            self.assertEqual(dash["EnvironmentVariables"]["PORT"], "8888")
            self.assertEqual(
                dash["ProgramArguments"], ["/bin/bash", legacy + "/scripts/meta/start_dashboard.sh"]
            )

    def test_named_project_gets_its_own_labels_paths_and_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / ".operacao-ia"
            p = tpa_paths.create_project("cliente-a", base, port_free=lambda _p: True)
            plists = self._render_all(p)
            home = str(base / "tpa-projetos" / "cliente-a")
            for base_label, data in plists.items():
                self.assertEqual(data["Label"], base_label + ".cliente-a")
                joined = json.dumps(data)
                self.assertIn(home, joined)
                self.assertNotIn(str(base / "scripts"), joined)  # nada aponta pro projeto padrão
            self.assertEqual(plists["com.zxlab.meta-dashboard-server"]["EnvironmentVariables"]["PORT"], "8889")

    def test_two_projects_never_share_a_label_or_a_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / ".operacao-ia"
            a = tpa_paths.create_project("a", base, port_free=lambda _p: True)
            b = tpa_paths.create_project("b", base, port_free=lambda _p: True)
            pa, pb = self._render_all(a), self._render_all(b)
            labels = [d["Label"] for d in list(pa.values()) + list(pb.values())]
            self.assertEqual(len(labels), len(set(labels)))
            self.assertNotEqual(
                pa["com.zxlab.meta-dashboard-server"]["EnvironmentVariables"]["PORT"],
                pb["com.zxlab.meta-dashboard-server"]["EnvironmentVariables"]["PORT"],
            )

    def test_cron_lines_point_to_the_project_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / ".operacao-ia"
            p = tpa_paths.create_project("cliente-a", base, port_free=lambda _p: True)
            lines = tpa_paths.cron_lines(p)
            self.assertEqual(len(lines), 2)
            for line in lines:
                self.assertIn(str(p.scripts_meta), line)
                self.assertTrue(line.endswith("# tpa:cliente-a"))
            default_lines = tpa_paths.cron_lines(tpa_paths.Paths("default", base))
            self.assertIn(str(base / "scripts" / "meta" / "run_fetch.sh"), default_lines[0])


class HardeningTest(unittest.TestCase):
    """Casos que o review adversarial apontou: nada pode cair em silencio no projeto padrao."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve() / ".operacao-ia"

    def tearDown(self):
        self._tmp.cleanup()

    def test_name_with_trailing_newline_is_rejected(self):
        for bad in ("default\n", "cliente-a\n", "ativo\n"):
            with self.assertRaises(tpa_paths.TpaError, msg=repr(bad)):
                tpa_paths.validate_name(bad)
            with self.assertRaises(tpa_paths.TpaError, msg=repr(bad)):
                tpa_paths.create_project(bad, self.base)

    def test_empty_or_unreadable_pointer_is_an_error_not_default(self):
        (self.base / "tpa-projetos").mkdir(parents=True)
        pointer = self.base / "tpa-projetos" / "ativo"
        pointer.write_text("\n")
        with patch.dict(os.environ, {"HOME": str(self.base.parent)}, clear=True):
            with self.assertRaises(tpa_paths.TpaError):
                tpa_paths.resolve()
        pointer.unlink()
        pointer.mkdir()  # ler um diretorio como arquivo: erro de leitura que nao e "ausente"
        with patch.dict(os.environ, {"HOME": str(self.base.parent)}, clear=True):
            with self.assertRaises(tpa_paths.TpaError):
                tpa_paths.resolve()

    def test_non_dict_project_file_is_handled(self):
        p = tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        p.project_file.write_text("null")
        self.assertEqual(tpa_paths.read_project_file("a", self.base), {})
        with self.assertRaises(tpa_paths.TpaError):
            tpa_paths.Paths("a", self.base).port
        with self.assertRaises(tpa_paths.TpaError):  # nao cria outro com a porta dele "livre"
            tpa_paths.create_project("b", self.base, port_free=lambda _p: True)
        self.assertFalse((self.base / "tpa-projetos" / "b").exists())

    def test_failed_create_leaves_no_half_made_project(self):
        with self.assertRaises(tpa_paths.TpaError):
            tpa_paths.create_project("x", self.base, port_free=lambda _p: False)
        self.assertFalse((self.base / "tpa-projetos" / "x").exists())

    def test_cron_lines_quote_paths_with_spaces_and_percent(self):
        base = Path(self._tmp.name).resolve() / "Maria Silva" / "100%"
        p = tpa_paths.create_project("a", base, port_free=lambda _p: True)
        for line in tpa_paths.cron_lines(p):
            self.assertIn("'", line)
            self.assertNotIn("%", line.replace("\\%", ""))

    def test_installed_copy_warns_when_env_points_elsewhere(self):
        import io
        from contextlib import redirect_stderr

        tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        dst = tpa_paths.sync_helper(self.base / "tpa-projetos" / "a" / "scripts" / "meta")
        err = io.StringIO()
        with redirect_stderr(err):
            p = tpa_paths.active_paths(env={"TPA_PROJECT": "outro", "HOME": str(self.base.parent)}, file=str(dst))
        self.assertEqual(p.name, "a")
        self.assertIn("TPA_PROJECT=outro ignorada", err.getvalue())

    def test_port_must_be_in_range_and_unique(self):
        a = tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        b = tpa_paths.create_project("b", self.base, port_free=lambda _p: True)
        data = json.loads(b.project_file.read_text())
        for bad in (8888, 80, 70000, True):
            data["porta"] = bad
            b.project_file.write_text(json.dumps(data))
            with self.assertRaises(tpa_paths.TpaError, msg=repr(bad)):
                tpa_paths.Paths("b", self.base).port
        data["porta"] = a.port  # pasta copiada a mao: mesma porta do original
        b.project_file.write_text(json.dumps(data))
        with self.assertRaises(tpa_paths.TpaError):
            tpa_paths.Paths("b", self.base).port
        with self.assertRaises(tpa_paths.TpaError):
            tpa_paths.Paths("a", self.base).port

    def test_legacy_base_inside_a_folder_named_tpa_projetos_stays_default(self):
        base = Path(self._tmp.name).resolve() / "tpa-projetos" / "operacao"
        dst = tpa_paths.sync_helper(base / "scripts" / "meta")
        self.assertEqual(tpa_paths.installed_location(str(dst)), (tpa_paths.DEFAULT_NAME, base))

    def test_relative_operacao_ia_home_becomes_absolute(self):
        self.assertTrue(tpa_paths.base_dir({"OPERACAO_IA_HOME": "relativa/pasta"}).is_absolute())

    def test_pointer_removal_failure_is_not_swallowed(self):
        tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        pointer = self.base / "tpa-projetos" / "ativo"
        pointer.unlink()
        pointer.mkdir()  # nao e arquivo: unlink falha com erro que NAO e "ausente"
        with self.assertRaises(tpa_paths.TpaError):
            tpa_paths.set_active("default", self.base)

    def test_shell_wrappers_refuse_to_fall_back_to_default_inside_a_project(self):
        import subprocess

        meta = self.base / "tpa-projetos" / "a" / "scripts" / "meta"
        meta.mkdir(parents=True)
        for name in ("run_fetch.sh", "start_dashboard.sh"):
            shutil.copy2(str(REPO / "scripts" / name), str(meta / name))  # sem tpa_paths.py
            r = subprocess.run(["bash", str(meta / name)], capture_output=True, text=True, timeout=20,
                               env={"PATH": os.environ.get("PATH", ""), "HOME": str(self.base.parent)},
                               stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 1, name + r.stdout + r.stderr)
            self.assertIn("pertence a um projeto", r.stderr)

    # ---- passada 3
    def test_symlinked_helper_keeps_the_project_where_the_link_lives(self):
        tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        tpa_paths.create_project("b", self.base, port_free=lambda _p: True)
        tpa_paths.set_active("b", self.base)
        meta = self.base / "tpa-projetos" / "a" / "scripts" / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        link = meta / "tpa_paths.py"
        link.symlink_to(REPO / "scripts" / "tpa_paths.py")
        self.assertEqual(tpa_paths.installed_location(str(link))[0], "a")

    def test_sync_helper_replaces_a_symlink_instead_of_writing_through_it(self):
        tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        meta = self.base / "tpa-projetos" / "a" / "scripts" / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        target = Path(self._tmp.name) / "alvo.py"
        target.write_text("# nao mexer\n")
        (meta / "tpa_paths.py").symlink_to(target)
        dst = tpa_paths.sync_helper(meta)
        self.assertFalse(dst.is_symlink())
        self.assertEqual(target.read_text(), "# nao mexer\n")

    def test_named_project_missing_projeto_json_fails_instead_of_default(self):
        tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        broken = self.base / "tpa-projetos" / "b" / "scripts" / "meta"
        broken.mkdir(parents=True)
        with self.assertRaises(tpa_paths.TpaError):
            tpa_paths.installed_location(str(broken / "tpa_paths.py"))

    def test_reserved_folder_name_in_projects_dir_is_refused_and_not_listed(self):
        tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        fake = self.base / "tpa-projetos" / "default"
        shutil.copytree(self.base / "tpa-projetos" / "a", fake)
        with self.assertRaises(tpa_paths.TpaError):
            tpa_paths.installed_location(str(fake / "scripts" / "meta" / "tpa_paths.py"))
        names = [n for n, _ in tpa_paths.list_projects(self.base)]
        self.assertEqual(names.count("default"), 1)

    def test_plist_escapes_xml_in_paths(self):
        base = Path(self._tmp.name) / "Clientes & Cia <x>"
        p = tpa_paths.Paths("default", base)
        tpl = "<plist><string>{OPERACAO}</string><string>{HOME}</string><string>{PYTHON}</string></plist>"
        out = tpa_paths.render_plist(tpl, p, "com.zxlab.meta-fetch", "/usr/bin/python3")
        self.assertIn("Clientes &amp; Cia &lt;x&gt;", out)
        import xml.dom.minidom
        xml.dom.minidom.parseString(out)  # continua XML valido

    def test_invalid_folder_name_in_projects_dir_fails(self):
        tpa_paths.create_project("a", self.base, port_free=lambda _p: True)
        bad = self.base / "tpa-projetos" / "Cliente-Silva" / "scripts" / "meta"
        bad.mkdir(parents=True)
        with self.assertRaises(tpa_paths.TpaError):
            tpa_paths.installed_location(str(bad / "tpa_paths.py"))

    def test_token_with_shell_metacharacters_is_refused(self):
        import subprocess
        home = Path(self._tmp.name) / "h"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), OPERACAO_IA_HOME=str(home / "op"))
        env.pop("TPA_PROJECT", None)
        bad = "EAAG" + "a" * 50 + "$(touch /tmp/tpa-pwn)"
        r = subprocess.run([sys.executable, str(REPO / "setup" / "setup_meta_oauth.py"), "--set-token", bad],
                           env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((home / "op" / "config" / "meta.env").exists())


class SwitchingProjectsEndToEndTest(unittest.TestCase):
    """Os scripts REAIS, em subprocesso, num HOME temporario: nada toca a maquina de quem roda."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.base = self.tmp / ".operacao-ia"
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.tmp),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, script, *args, **extra_env):
        import subprocess

        env = dict(self.env, **extra_env)
        return subprocess.run(
            [sys.executable, str(REPO / script), *args],
            env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        )

    def _account(self, project_dir):
        text = (project_dir / "config" / "meta.env").read_text()
        return [l for l in text.splitlines() if l.startswith("META_AD_ACCOUNT_ID=")][0].split("=", 1)[1]

    def test_second_client_does_not_overwrite_the_first(self):
        # cliente 1 no projeto padrao (instalacao antiga, sem nenhum projeto criado)
        r = self._run("setup/setup_meta_oauth.py", "--set-account", "act_111")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._account(self.base), "act_111")

        # cliente 2: projeto novo
        r = self._run("setup/tpa_projeto.py", "criar", "cliente-b")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self._run("setup/setup_meta_oauth.py", "--set-account", "act_222")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        proj_b = self.base / "tpa-projetos" / "cliente-b"
        self.assertEqual(self._account(proj_b), "act_222")
        self.assertEqual(self._account(self.base), "act_111")  # intacto

        # volta para o cliente 1 e confirma que o 2 segue como estava
        r = self._run("setup/tpa_projeto.py", "trocar", "default")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # trocar a conta DENTRO do mesmo projeto e recusado sem a flag explicita
        r = self._run("setup/setup_meta_oauth.py", "--set-account", "act_112")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("tpa_projeto.py criar", r.stdout)
        self.assertEqual(self._account(self.base), "act_111")
        r = self._run("setup/setup_meta_oauth.py", "--set-account", "act_112", "--substituir-conta")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._account(self.base), "act_112")
        self.assertEqual(self._account(proj_b), "act_222")  # o outro cliente nunca muda

    def test_env_var_targets_a_project_without_switching_the_active_one(self):
        self._run("setup/tpa_projeto.py", "criar", "cliente-b")
        self._run("setup/tpa_projeto.py", "trocar", "default")
        r = self._run("setup/setup_meta_oauth.py", "--set-account", "act_333", TPA_PROJECT="cliente-b")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self._account(self.base / "tpa-projetos" / "cliente-b"), "act_333")
        self.assertFalse((self.base / "config" / "meta.env").exists())  # padrao nao foi criado/alterado
        r = self._run("setup/tpa_projeto.py", "atual")
        self.assertIn("default", r.stdout)

    def test_unknown_project_in_env_aborts_instead_of_writing_to_default(self):
        r = self._run("setup/setup_meta_oauth.py", "--set-account", "act_444", TPA_PROJECT="fantasma")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.base / "config" / "meta.env").exists())

    def test_cli_lists_projects_and_refuses_unknown_switch(self):
        self._run("setup/tpa_projeto.py", "criar", "cliente-a")
        r = self._run("setup/tpa_projeto.py", "listar")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("cliente-a", r.stdout)
        self.assertIn("default", r.stdout)
        r = self._run("setup/tpa_projeto.py", "trocar", "nao-existe")
        self.assertEqual(r.returncode, 1)
        r = self._run("setup/tpa_projeto.py", "atual")
        self.assertIn("cliente-a", r.stdout)  # a troca falha nao mexeu no ativo


if __name__ == "__main__":
    unittest.main()
