"""check_api_version.py: rede sempre stubada (nenhuma chamada real à Meta)."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_api_version as cav  # noqa: E402
import tpa_paths  # noqa: E402
from report_formatter import assemble_report, render_whatsapp  # noqa: E402

NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


def _project(tmp, version="v21.0", token="TOKEN_FALSO", name="default"):
    base = Path(tmp)
    p = tpa_paths.Paths(name, base)
    for d in (p.config_dir, p.scripts_meta, p.dashboards, p.logs):
        d.mkdir(parents=True, exist_ok=True)
    if token is not None:
        p.meta_env.write_text("META_ACCESS_TOKEN=%s\nMETA_AD_ACCOUNT_ID=act_1\n" % token, encoding="utf-8")
    (p.scripts_meta / "fetch_metrics.py").write_text(
        'GRAPH_BASE = "https://graph.facebook.com/%s"\n' % version, encoding="utf-8"
    )
    return p


def _fetcher(status=200, headers=None, body="{\"id\": \"1\"}", calls=None):
    def fetch(url, token, timeout=30):
        if calls is not None:
            calls.append((url, token))
        return status, {k.lower(): v for k, v in (headers or {}).items()}, body

    return fetch


class AnalyzeResponseTest(unittest.TestCase):
    def test_ok_without_warnings(self):
        level, msgs, _ = cav.analyze_response("v21.0", 200, {"facebook-api-version": "v21.0"}, "{}", now=NOW)
        self.assertEqual((level, msgs), ("ok", []))

    def test_served_version_differs_is_critical(self):
        level, msgs, rel = cav.analyze_response("v21.0", 200, {"facebook-api-version": "v23.0"}, "{}", now=NOW)
        self.assertEqual(level, "critico")
        self.assertIn("v23.0", msgs[0])
        self.assertEqual(rel["facebook-api-version"], "v23.0")

    def test_sunset_within_window_is_attention(self):
        headers = {"facebook-api-version": "v21.0", "sunset": "Sat, 10 Jan 2027 00:00:00 GMT"}
        level, msgs, _ = cav.analyze_response("v21.0", 200, headers, "{}", now=NOW, dias=60)
        self.assertEqual(level, "atencao")
        self.assertIn("faltam", msgs[0])

    def test_sunset_far_away_stays_ok_but_is_reported(self):
        headers = {"sunset": "Sat, 10 Jan 2028 00:00:00 GMT"}
        level, msgs, _ = cav.analyze_response("v21.0", 200, headers, "{}", now=NOW, dias=60)
        self.assertEqual(level, "ok")
        self.assertTrue(msgs)

    def test_sunset_in_the_past_is_critical(self):
        level, _m, _r = cav.analyze_response("v21.0", 200, {"sunset": "Sat, 10 Jan 2026 00:00:00 GMT"}, "{}", now=NOW)
        self.assertEqual(level, "critico")

    def test_unreadable_sunset_is_attention(self):
        level, _m, _r = cav.analyze_response("v21.0", 200, {"sunset": "logo"}, "{}", now=NOW)
        self.assertEqual(level, "atencao")

    def test_deprecation_and_warning_headers(self):
        for name in ("deprecation", "x-fb-deprecated-thing", "warning"):
            level, _m, rel = cav.analyze_response("v21.0", 200, {name: "true"}, "{}", now=NOW)
            self.assertEqual(level, "atencao", name)
            self.assertIn(name, rel)

    def test_deprecated_error_text_is_critical(self):
        body = json.dumps({"error": {"message": "(#2635) You are calling a deprecated version of the Ads API", "code": 2635}})
        level, _m, _r = cav.analyze_response("v21.0", 400, {}, body, now=NOW)
        self.assertEqual(level, "critico")

    def test_version_no_longer_supported_text_is_critical(self):
        body = json.dumps({"error": {"message": "Graph API version v17.0 is no longer available", "code": 2635}})
        level, _m, _r = cav.analyze_response("v17.0", 400, {}, body, now=NOW)
        self.assertEqual(level, "critico")

    def test_invalid_token_is_error_with_renew_hint(self):
        body = json.dumps({"error": {"message": "Invalid OAuth access token", "code": 190}})
        level, msgs, _ = cav.analyze_response("v21.0", 401, {}, body, now=NOW)
        self.assertEqual(level, "erro")
        self.assertIn("--renew", msgs[0])

    def test_aviso_dias_env_override_and_invalid_values(self):
        self.assertEqual(cav.aviso_dias({"ZX_TPA_API_AVISO_DIAS": "90"}), 90)
        for bad in ("", "abc", "0", "-5"):
            self.assertEqual(cav.aviso_dias({"ZX_TPA_API_AVISO_DIAS": bad}), cav.AVISO_DIAS_PADRAO, bad)


class VersionDetectionTest(unittest.TestCase):
    def test_detects_versions_in_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "fetch_metrics.py").write_text('B = "https://graph.facebook.com/v22.0"\n', encoding="utf-8")
            (d / "outro.py").write_text('B = "https://graph.facebook.com/v21.0/x"\n', encoding="utf-8")
            found = cav.detect_versions([d])
            self.assertEqual(found["fetch_metrics.py"], "v22.0")
            self.assertEqual(cav.pick_version(found), "v22.0")  # o coletor manda

    def test_no_version_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cav.detect_versions([Path(tmp)]), {})
            self.assertIsNone(cav.pick_version({}))


class CheckProjectTest(unittest.TestCase):
    def test_writes_status_file_and_uses_stub_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            calls = []
            result = cav.check_project(
                p, now=NOW,
                fetcher=_fetcher(headers={"facebook-api-version": "v21.0"}, calls=calls),
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["versao_em_uso"], "v21.0")
            self.assertEqual(len(calls), 1)
            self.assertIn("/v21.0/me", calls[0][0])
            saved = json.loads((p.dashboards / "api-status.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "ok")
            self.assertNotIn("TOKEN_FALSO", json.dumps(saved))

    def test_critical_when_meta_serves_another_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            result = cav.check_project(
                p, now=NOW,
                fetcher=_fetcher(headers={"facebook-api-version": "v23.0"}),
            )
            self.assertEqual(result["status"], "critico")
            self.assertEqual(result["versao_servida"], "v23.0")

    def test_missing_token_makes_no_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, token=None)
            calls = []
            result = cav.check_project(p, now=NOW, fetcher=_fetcher(calls=calls))
            self.assertEqual(result["status"], "nao_verificado")
            self.assertEqual(calls, [])

    def test_network_failure_is_reported_not_raised(self):
        def boom(url, token, timeout=30):
            raise OSError("sem rede")

        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            result = cav.check_project(p, now=NOW, fetcher=boom)
            self.assertIn(result["status"], ("erro", "nao_verificado"))


class RobustnessTest(unittest.TestCase):
    def test_http_client_exception_is_reported_and_status_file_written(self):
        import http.client

        def boom(url, token, timeout=30):
            raise http.client.IncompleteRead(b"x")

        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            result = cav.check_project(p, now=NOW, fetcher=boom)
            self.assertEqual(result["status"], "erro")
            self.assertTrue((p.dashboards / "api-status.json").exists())

    def test_unwritable_status_file_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            (p.dashboards / "api-status.json").mkdir()  # um diretório no lugar do arquivo: a gravação falha
            result = cav.check_project(p, now=NOW,
                                       fetcher=_fetcher(headers={"facebook-api-version": "v21.0"}))
            self.assertFalse(result["gravado_em_disco"])

    def test_error_is_not_hidden_behind_attention_in_exit_order(self):
        self.assertGreater(cav._exit_rank("erro"), cav._exit_rank("atencao"))
        self.assertGreater(cav._exit_rank("nao_verificado"), cav._exit_rank("atencao"))
        self.assertGreater(cav._exit_rank("critico"), cav._exit_rank("erro"))

    def test_schedule_creates_logs_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            shutil.rmtree(p.logs)
            self.assertFalse(p.logs.exists())
            old = dict(os.environ)
            os.environ["OPERACAO_IA_HOME"] = tmp
            os.environ.pop("TPA_PROJECT", None)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    cav.main(["--agendamento"])
            finally:
                os.environ.clear()
                os.environ.update(old)
            self.assertTrue(p.logs.is_dir())


class DetectionAndMultiVersionTest(unittest.TestCase):
    def test_each_distinct_version_is_checked_and_divergence_is_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, version="v22.0")
            (p.scripts_meta / "outro.py").write_text('B = "https://graph.facebook.com/v19.0/x"\n', encoding="utf-8")
            calls = []

            def fetch(url, token, timeout=30):
                calls.append(url)
                served = "v22.0" if "/v22.0/" in url else "v21.0"  # a v19.0 já foi encerrada: a Meta serve outra
                return 200, {"facebook-api-version": served}, "{}"

            result = cav.check_project(p, now=NOW, fetcher=fetch)
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["status"], "critico")
            self.assertTrue(any("[v19.0]" in m for m in result["mensagens"]))

    def test_divergent_versions_without_warnings_is_at_least_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, version="v22.0")
            (p.scripts_meta / "outro.py").write_text('B = "https://graph.facebook.com/v21.0/x"\n', encoding="utf-8")

            def fetch(url, token, timeout=30):
                return 200, {"facebook-api-version": "v22.0" if "/v22.0/" in url else "v21.0"}, "{}"

            result = cav.check_project(p, now=NOW, fetcher=fetch)
            self.assertEqual(result["status"], "atencao")

    def test_project_folder_without_version_does_not_fall_back_to_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            (p.scripts_meta / "fetch_metrics.py").write_text("print('sem versao fixa')\n", encoding="utf-8")
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "fetch_metrics.py").write_text('B = "https://graph.facebook.com/v22.0/x"\n', encoding="utf-8")
            calls = []
            result = cav.check_project(p, now=NOW, fetcher=_fetcher(calls=calls))
            self.assertEqual(result["status"], "nao_verificado")
            self.assertEqual(calls, [])

    def test_missing_project_scripts_folder_is_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            shutil.rmtree(p.scripts_meta)
            calls = []
            result = cav.check_project(p, now=NOW, fetcher=_fetcher(calls=calls))
            self.assertEqual(result["status"], "nao_verificado")
            self.assertEqual(calls, [])

    def test_versions_in_comments_and_docstrings_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "a.py").write_text(
                '"""migrado de graph.facebook.com/v15.0"""\n# antes: https://graph.facebook.com/v16.0/x\n'
                'B = "https://graph.facebook.com/v22.0/x"\n', encoding="utf-8")
            self.assertEqual(cav.detect_versions([d]), {"a.py": "v22.0"})

    def test_unverified_version_is_not_hidden_behind_a_warning_of_another(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, version="v21.0")
            (p.scripts_meta / "outro.py").write_text('B = "https://graph.facebook.com/v22.0/x"\n', encoding="utf-8")

            def fetch(url, token, timeout=30):
                if "/v22.0/" in url:
                    raise OSError("timeout")
                return 200, {"facebook-api-version": "v21.0", "warning": "algo"}, "{}"

            result = cav.check_project(p, now=NOW, fetcher=fetch)
            self.assertEqual(result["status"], "erro")

    def test_env_with_invalid_bytes_is_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            p.meta_env.write_bytes(b"META_ACCESS_TOKEN=\xff\xfe\x00bad\n")
            result = cav.check_project(p, now=NOW, fetcher=_fetcher())
            self.assertIn(result["status"], ("nao_verificado", "ok", "erro", "atencao", "critico"))

    def test_schedule_fails_loudly_when_logs_folder_cannot_be_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            shutil.rmtree(p.logs)
            p.logs.write_text("sou um arquivo", encoding="utf-8")  # mkdir vai falhar
            old = dict(os.environ)
            os.environ["OPERACAO_IA_HOME"] = tmp
            os.environ.pop("TPA_PROJECT", None)
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = cav.main(["--agendamento"])
            finally:
                os.environ.clear()
                os.environ.update(old)
            self.assertEqual(code, 3)


class MainAndScheduleTest(unittest.TestCase):
    def test_schedule_lines_cover_three_systems_and_name_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, name="cliente-a")
            text = "\n".join(cav.schedule_help(p, script_path="/x/check_api_version.py", python="/usr/bin/python3"))
            self.assertIn("17 9 * * 1", text)
            self.assertIn("--projeto cliente-a", text)
            self.assertIn("schtasks", text)
            self.assertIn("launchd", text)
            self.assertIn("ZXLab Meta API Check - cliente-a", text)

    def test_exit_codes_follow_severity(self):
        self.assertEqual([cav.EXIT_CODES[k] for k in ("ok", "atencao", "critico", "erro")], [0, 1, 2, 3])
        self.assertGreater(cav._rank("critico"), cav._rank("erro"))


class PassFourTest(unittest.TestCase):
    def test_warning_header_does_not_hide_a_failed_call(self):
        body = json.dumps({"error": {"code": 190, "message": "token expirado"}})
        level, _msgs, _rel = cav.analyze_response("v21.0", 401, {"warning": "x", "facebook-api-version": "v21.0"},
                                                   body, now=NOW)
        self.assertEqual(level, "erro")
        self.assertEqual(cav.EXIT_CODES[level], 3)

    def test_env_value_with_quotes_and_export_is_read_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "meta.env"
            f.write_text('export META_ACCESS_TOKEN="EAAG123"\nOUTRO=\'x\'\n', encoding="utf-8")
            self.assertEqual(cav._read_env(f, "META_ACCESS_TOKEN"), "EAAG123")
            self.assertEqual(cav._read_env(f, "OUTRO"), "x")

    def test_unwritable_surrogate_text_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            res = {"status": "erro", "mensagens": ["ruim \udc80"]}
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertFalse(cav._write_status(p, res))

    def test_unexpected_exception_in_one_project_exits_3_and_keeps_going(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp)
            old_active, old_check = tpa_paths.active_paths, cav.check_project
            tpa_paths.active_paths = lambda: p
            cav.check_project = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = cav.main([])
            finally:
                tpa_paths.active_paths, cav.check_project = old_active, old_check
            self.assertEqual(code, 3)

    def test_expired_token_mentioning_no_longer_is_an_error_not_a_dead_version(self):
        body = json.dumps({"error": {"code": 190, "message": "Session is no longer valid"}})
        level, msgs, _rel = cav.analyze_response("v21.0", 400, {}, body, now=NOW)
        self.assertEqual(level, "erro")
        self.assertIn("setup_meta_oauth.py --renew", msgs[0])

    def test_redirect_is_not_followed_and_is_reported_as_error(self):
        self.assertIsNone(cav._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://outro.example/x"))
        level, msgs, _rel = cav.analyze_response("v21.0", 302, {"location": "https://outro.example/"}, "", now=NOW)
        self.assertEqual(level, "erro")
        self.assertTrue(msgs)

    def test_unresolvable_project_exits_3(self):
        old = tpa_paths.active_paths
        def boom():
            raise tpa_paths.TpaError("projeto inexistente")
        tpa_paths.active_paths = boom
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cav.main([]), 3)
        finally:
            tpa_paths.active_paths = old

    def test_windows_line_quotes_the_project_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _project(tmp, name="cliente-a")
            text = "\n".join(cav.schedule_help(p, script_path="/x/c.py", python="/usr/bin/python3"))
            self.assertIn('--projeto \\"cliente-a\\""', text)


class ReportIntegrationTest(unittest.TestCase):
    def _report_dir(self, tmp, api_status):
        base = Path(tmp)
        (base / "config").mkdir()
        (base / "dashboards").mkdir()
        (base / "config" / "meta_perfil.json").write_text(
            json.dumps({"windows": [7], "ad_account_id": "act_1", "primary_kpi": "cpl", "kpis": []}), encoding="utf-8")
        (base / "dashboards" / "paid-traffic-7d.json").write_text(json.dumps({
            "generated_at": NOW.isoformat(), "window_days": 7, "ad_account_id": "act_1", "currency": "BRL",
            "primary_kpi": "cpl", "kpis_summary": {}, "spend_total": 10, "campaigns": []}), encoding="utf-8")
        if api_status is not None:
            (base / "dashboards" / "api-status.json").write_text(json.dumps(api_status), encoding="utf-8")
        return base

    def test_attention_status_reaches_report_and_whatsapp(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._report_dir(tmp, {"status": "atencao", "mensagens": ["A Meta enviou o aviso 'deprecation: true'."]})
            report = assemble_report(7, operation_dir=base, now=NOW)
            self.assertIn("API META", report["warning"])
            self.assertIn("API META", render_whatsapp(report))

    def test_whatsapp_keeps_the_action_even_with_stale_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._report_dir(tmp, {"status": "critico", "checked_at": "2026-11-20T09:00:00-03:00",
                                          "mensagens": ["A Meta respondeu com a versão v22.0, mas o sistema pediu v21.0: " * 3]})
            path = base / "dashboards" / "paid-traffic-7d.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["generated_at"] = (NOW - timedelta(hours=40)).isoformat()
            path.write_text(json.dumps(data), encoding="utf-8")
            text = render_whatsapp(assemble_report(7, operation_dir=base, now=NOW))
            self.assertIn("DADO DEFASADO", text)
            self.assertIn("check_api_version.py", text)  # o WhatsApp corta o aviso: a ação não pode ser o que some

    def test_malformed_messages_field_never_breaks_the_report(self):
        for bad in ({"x": 1}, 5, "texto", [None]):
            with tempfile.TemporaryDirectory() as tmp:
                base = self._report_dir(tmp, {"status": "critico", "mensagens": bad, "checked_at": "2026-11-20T09:00:00-03:00"})
                report = assemble_report(7, operation_dir=base, now=NOW)
                self.assertIn("API META URGENTE", report["warning"])
                self.assertIn("2026-11-20", report["warning"])  # a data da checagem aparece no aviso

    def test_ok_or_missing_status_adds_nothing(self):
        for status in ({"status": "ok", "mensagens": []}, None):
            with tempfile.TemporaryDirectory() as tmp:
                base = self._report_dir(tmp, status)
                self.assertEqual(assemble_report(7, operation_dir=base, now=NOW)["warning"], "")

    def test_corrupt_status_file_never_breaks_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._report_dir(tmp, None)
            (base / "dashboards" / "api-status.json").write_text("{quebrado", encoding="utf-8")
            warning = assemble_report(7, operation_dir=base, now=NOW)["warning"]
            self.assertIn("ilegível", warning)  # arquivo existente e quebrado não some em silêncio
            self.assertIn("check_api_version.py", warning)

    def test_error_status_is_reported_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._report_dir(tmp, {"status": "erro", "mensagens": ["A Meta recusou o token"]})
            self.assertIn("não conseguiu confirmar", assemble_report(7, operation_dir=base, now=NOW)["warning"])

    def test_unavailable_report_still_carries_the_api_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._report_dir(tmp, {"status": "critico", "mensagens": ["versão encerrada"]})
            (base / "dashboards" / "paid-traffic-7d.json").unlink()
            report = assemble_report(7, operation_dir=base, now=NOW)
            self.assertFalse(report["available"])
            self.assertIn("API META URGENTE", report["warning"])

    def test_long_generated_at_error_cannot_push_the_api_action_out_of_whatsapp(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._report_dir(tmp, {"status": "atencao", "mensagens": ["aviso"]})
            path = base / "dashboards" / "paid-traffic-7d.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["generated_at"] = "x" * 300
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertIn("check_api_version.py", render_whatsapp(assemble_report(7, operation_dir=base, now=NOW)))


if __name__ == "__main__":
    unittest.main()
