"""dashboard_agencia.py: lê JSONs de projetos em pasta temporária; sem rede."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dashboard_agencia as da  # noqa: E402
import tpa_paths  # noqa: E402

NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


def _make(base, name, kpi, currency, spend, raws, generated=None, api=None, account="act_1"):
    if name == "default":
        p = tpa_paths.Paths("default", base)
    else:
        home = tpa_paths.projects_dir(base) / name
        home.mkdir(parents=True, exist_ok=True)
        (home / tpa_paths.PROJECT_FILE).write_text("{}", encoding="utf-8")
        p = tpa_paths.Paths(name, base)
    p.config_dir.mkdir(parents=True, exist_ok=True)
    p.dashboards.mkdir(parents=True, exist_ok=True)
    p.meta_env.write_text("META_AD_ACCOUNT_ID=%s\nMETA_ACCESS_TOKEN=SEGREDO_NAO_VAZAR\n" % account, encoding="utf-8")
    (p.dashboards / "paid-traffic-7d.json").write_text(json.dumps({
        "generated_at": (generated or NOW).isoformat(), "window_days": 7, "currency": currency,
        "primary_kpi": kpi, "spend_total": spend, "raws_total": raws,
        "kpis_summary": {kpi: {"value": 1, "target": 2, "status": "green"}}}), encoding="utf-8")
    if api:
        (p.dashboards / "api-status.json").write_text(json.dumps({"status": api}), encoding="utf-8")
    return p


class CollectTest(unittest.TestCase):
    def test_lead_client_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "cpl", "BRL", 500.0, {"spend": 500, "leads": 20})
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertEqual(row["erro"], "")
            self.assertEqual(row["resultado"], 20.0)
            self.assertEqual(row["resultado_tipo"], "leads")
            self.assertAlmostEqual(row["custo_por_resultado"], 25.0)
            self.assertIsNone(row["roas"])  # sem valor de compra não existe ROAS
            self.assertIsNone(row["cpa"])

    def test_purchase_client_computes_cpa_and_roas_from_raws(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "roas", "BRL", 300.0, {"spend": 300, "purchases": 5, "purchase_value": 900})
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertAlmostEqual(row["cpa"], 60.0)
            self.assertAlmostEqual(row["roas"], 3.0)
            self.assertAlmostEqual(row["custo_por_resultado"], 60.0)

    def test_missing_window_is_an_error_row_not_an_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "cpl", "BRL", 10, {"leads": 1})
            row = da.collect_client("default", p, 30, now=NOW)
            self.assertIn("sem coleta", row["erro"])

    def test_corrupt_json_is_an_error_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "cpl", "BRL", 10, {"leads": 1})
            (p.dashboards / "paid-traffic-7d.json").write_text("{quebrado", encoding="utf-8")
            self.assertIn("sem coleta", da.collect_client("default", p, 7, now=NOW)["erro"])

    def test_stale_and_api_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = NOW - timedelta(hours=30)
            p = _make(Path(tmp), "default", "cpl", "BRL", 10, {"leads": 1}, generated=old, api="critico")
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertTrue(row["defasado"])
            self.assertEqual(row["api_status"], "critico")
            fresh = _make(Path(tmp) / "b", "default", "cpl", "BRL", 10, {"leads": 1})
            self.assertFalse(da.collect_client("default", fresh, 7, now=NOW)["defasado"])

    def test_api_error_status_is_visible_in_text_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "cpl", "BRL", 10, {"leads": 1}, api="erro")
            row = da.collect_client("default", p, 7, now=NOW)
            totals = da.build_totals([row])
            self.assertIn("API Meta: erro", da.render_text([row], totals, 7))
            self.assertIn("erro", da.render_html([row], totals, 7).split("API Meta</th>", 1)[1])


class RobustnessTest(unittest.TestCase):
    def _raw(self, tmp, payload):
        p = _make(Path(tmp), "default", "cpl", "BRL", 10, {"leads": 1})
        (p.dashboards / "paid-traffic-7d.json").write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_missing_currency_is_an_error_row_not_brl(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._raw(tmp, {"generated_at": NOW.isoformat(), "primary_kpi": "cpl", "spend_total": 50, "raws_total": {"leads": 2}})
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertIn("moeda", row["erro"])
            self.assertEqual(da.build_totals([row]), {})

    def test_null_spend_is_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._raw(tmp, {"generated_at": NOW.isoformat(), "currency": "BRL", "primary_kpi": "cpl",
                                "spend_total": None, "raws_total": {"leads": 2}})
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertIn("gasto", row["erro"])
            self.assertIsNone(row["gasto"])

    def test_spend_falls_back_to_raws_spend(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._raw(tmp, {"generated_at": NOW.isoformat(), "currency": "brl", "primary_kpi": "cpl",
                                "spend_total": None, "raws_total": {"spend": 80, "leads": 2}})
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertEqual(row["erro"], "")
            self.assertEqual(row["gasto"], 80.0)
            self.assertEqual(row["moeda"], "BRL")

    def test_malformed_shapes_never_raise(self):
        shapes = [
            {"currency": "BRL", "spend_total": 5, "raws_total": [1, 2], "kpis_summary": "x", "primary_kpi": "cpl"},
            {"currency": "BRL", "spend_total": 5, "raws_total": {}, "kpis_summary": [], "primary_kpi": ["cpl"]},
            {"currency": "BRL", "spend_total": 5, "raws_total": {}, "generated_at": 123},
            {"currency": 7, "spend_total": "abc"},
        ]
        for payload in shapes:
            with tempfile.TemporaryDirectory() as tmp:
                p = self._raw(tmp, payload)
                row = da.collect_client("default", p, 7, now=NOW)
                self.assertIn("projeto", row)

    def test_invalid_timeout_env_falls_back(self):
        for raw in ("abc", "0", "-5", ""):
            with self.subTest(raw=raw):
                os.environ["ZX_TPA_AGENCIA_FETCH_TIMEOUT"] = raw
                try:
                    self.assertEqual(da._timeout_from_env("ZX_TPA_AGENCIA_FETCH_TIMEOUT", 600), 600)
                finally:
                    del os.environ["ZX_TPA_AGENCIA_FETCH_TIMEOUT"]
        os.environ["ZX_TPA_AGENCIA_FETCH_TIMEOUT"] = "900"
        try:
            self.assertEqual(da._timeout_from_env("ZX_TPA_AGENCIA_FETCH_TIMEOUT", 600), 900)
        finally:
            del os.environ["ZX_TPA_AGENCIA_FETCH_TIMEOUT"]

    def test_collector_output_tokens_are_redacted(self):
        text = "GET ?access_token=EAABsbCS1iHgBOabcdef123456 Authorization: Bearer abcdefghijkl12345"
        out = da._redact(text)
        self.assertNotIn("EAABsbCS1iHgBOabcdef123456", out)
        self.assertNotIn("abcdefghijkl12345", out)


class RobustnessTwoTest(unittest.TestCase):
    def test_non_string_api_status_does_not_break_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "cpl", "BRL", 10, {"spend": 10, "leads": 1})
            (p.dashboards / "api-status.json").write_text(json.dumps({"status": ["ok"]}), encoding="utf-8")
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertIsNone(row["api_status"])
            html_out = da.render_html([row], da.build_totals([row]), 7)
            self.assertIn("<table>", html_out)

    def test_nan_and_negative_spend_are_error_rows(self):
        for bad in (float("nan"), float("inf"), -5):
            with tempfile.TemporaryDirectory() as tmp:
                p = _make(Path(tmp), "default", "cpl", "BRL", 10, {"leads": 1})
                (p.dashboards / "paid-traffic-7d.json").write_text(json.dumps(
                    {"generated_at": NOW.isoformat(), "currency": "BRL", "primary_kpi": "cpl",
                     "spend_total": bad, "raws_total": {"leads": 1}}), encoding="utf-8")
                row = da.collect_client("default", p, 7, now=NOW)
                self.assertIn("gasto", row["erro"])

    def test_unreadable_env_does_not_break_the_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "cpl", "BRL", 10, {"spend": 10, "leads": 1})
            p.meta_env.write_bytes(b"META_AD_ACCOUNT_ID=\xff\xfe\x00\n")
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertIn("projeto", row)

    def test_total_cpa_roas_are_not_diluted_by_clients_that_do_not_measure(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _make(Path(tmp), "default", "cpl", "BRL", 10000.0,
                      {"spend": 10000, "leads": 10, "purchases": 50, "purchase_value": 20000})
            b = _make(Path(tmp), "b", "cpl", "BRL", 10000.0, {"spend": 10000, "leads": 10})  # não mede compras
            rows = [da.collect_client("default", a, 7, now=NOW), da.collect_client("b", b, 7, now=NOW)]
            g = da.build_totals(rows)["BRL"]["grupos"]["cpl"]
            self.assertAlmostEqual(g["cpa"], 200.0)
            self.assertAlmostEqual(g["roas"], 2.0)
            self.assertTrue(g["cpa_parcial"])
            self.assertIn("parcial", da.render_text(rows, da.build_totals(rows), 7))


class RobustnessThreeTest(unittest.TestCase):
    def test_missing_result_is_not_zero_and_cost_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _make(Path(tmp), "default", "cpl", "BRL", 1000.0, {"spend": 1000, "leads": 50})
            b = _make(Path(tmp), "b", "cpl", "BRL", 500.0, {"spend": 500})  # leads não medidos
            rows = [da.collect_client("default", a, 7, now=NOW), da.collect_client("b", b, 7, now=NOW)]
            self.assertIsNone(rows[1]["resultado"])
            self.assertEqual(da._result_cell(rows[1]), "—")
            g = da.build_totals(rows)["BRL"]["grupos"]["cpl"]
            self.assertAlmostEqual(g["custo_por_resultado"], 20.0)  # só sobre quem mede leads
            self.assertTrue(g["custo_parcial"])

    def test_infinite_metrics_are_treated_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "cpa", "BRL", 100.0, {"spend": 100})
            (p.dashboards / "paid-traffic-7d.json").write_text(
                '{"generated_at": "%s", "currency": "BRL", "primary_kpi": "cpa", "spend_total": 100,'
                ' "raws_total": {"purchases": Infinity, "purchase_value": NaN}}' % NOW.isoformat(), encoding="utf-8")
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertIsNone(row["cpa"])
            self.assertIsNone(row["roas"])
            self.assertIsNone(row["resultado"])

    def test_redaction_covers_app_secret_pairs_and_client_secret(self):
        out = da._redact("url?access_token=1234567890123456|SEGREDOLONGO123&x=1 client_secret=ABCDEFGH12345678")
        self.assertNotIn("SEGREDOLONGO123", out)
        self.assertNotIn("ABCDEFGH12345678", out)

    def test_host_permitido_refuses_without_access_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = dict(os.environ)
            os.environ["OPERACAO_IA_HOME"] = tmp
            try:
                import contextlib
                import io
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = da.main(["--servir", "--host-permitido", "painel.exemplo.com"])
            finally:
                os.environ.clear()
                os.environ.update(old)
            self.assertEqual(code, 2)
            self.assertIn("--protegido-por-acesso", err.getvalue())


class TotalsTest(unittest.TestCase):
    def _rows(self, tmp):
        base = Path(tmp)
        specs = [
            ("default", "cpl", "BRL", 500.0, {"spend": 500, "leads": 20}),
            ("cli-b", "cpl", "BRL", 100.0, {"spend": 100, "leads": 10}),
            ("cli-c", "roas", "BRL", 300.0, {"spend": 300, "purchases": 5, "purchase_value": 900}),
            ("cli-d", "cpl", "USD", 50.0, {"spend": 50, "leads": 5}),
        ]
        return [da.collect_client(n, _make(base, n, k, c, s, r), 7, now=NOW) for n, k, c, s, r in specs]

    def test_currencies_and_result_types_are_never_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            totals = da.build_totals(self._rows(tmp))
            self.assertEqual(set(totals), {"BRL", "USD"})
            self.assertAlmostEqual(totals["BRL"]["gasto"], 900.0)
            self.assertAlmostEqual(totals["USD"]["gasto"], 50.0)
            cpl = totals["BRL"]["grupos"]["cpl"]
            self.assertEqual(cpl["resultado"], 30.0)
            self.assertAlmostEqual(cpl["custo_por_resultado"], 600.0 / 30.0)  # soma/soma, não média
            self.assertAlmostEqual(totals["BRL"]["grupos"]["roas"]["roas"], 3.0)
            self.assertEqual(totals["BRL"]["clientes"], 3)

    def test_error_rows_are_left_out_of_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self._rows(tmp)
            rows.append(da.collect_client("x", _make(Path(tmp) / "y", "default", "cpl", "BRL", 1, {"leads": 1}), 30, now=NOW))
            self.assertAlmostEqual(da.build_totals(rows)["BRL"]["gasto"], 900.0)


class ListAndRenderTest(unittest.TestCase):
    def test_lists_only_projects_with_account_or_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _make(base, "cli-a", "cpl", "BRL", 1, {"leads": 1})
            empty = tpa_paths.projects_dir(base) / "cli-vazio"
            empty.mkdir(parents=True)
            (empty / tpa_paths.PROJECT_FILE).write_text("{}", encoding="utf-8")
            self.assertEqual([n for n, _p in da.list_clients(base)], ["cli-a"])
            self.assertEqual([n for n, _p in da.list_clients(base, only={"cli-vazio"})], ["cli-vazio"])

    def test_html_escapes_and_never_leaks_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "cli-a", "cpl", "BRL", 10, {"leads": 1}, account="<script>x</script>")
            rows = [da.collect_client("cli-a", p, 7, now=NOW)]
            page = da.render_html(rows, da.build_totals(rows), 7, now=datetime(2026, 11, 21))
            self.assertNotIn("<script>x</script>", page)
            self.assertIn("&lt;script&gt;", page)
            self.assertNotIn("SEGREDO_NAO_VAZAR", page)
            self.assertNotIn("SEGREDO_NAO_VAZAR", da.render_text(rows, da.build_totals(rows), 7))

    def test_text_output_has_clients_and_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "roas", "BRL", 300.0, {"spend": 300, "purchases": 5, "purchase_value": 900})
            rows = [da.collect_client("default", p, 7, now=NOW)]
            text = da.render_text(rows, da.build_totals(rows), 7)
            self.assertIn("R$ 300,00", text)
            self.assertIn("3,00x", text)
            self.assertIn("TOTAL em BRL", text)

    def test_write_html_goes_to_agency_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = da.write_html(Path(tmp), [], {}, 7)
            self.assertEqual(target, Path(tmp) / "dashboard-agencia" / "index.html")
            self.assertTrue(target.is_file())


class RefreshTest(unittest.TestCase):
    def test_refresh_runs_collector_with_project_env_and_reports_failure(self):
        seen = {}

        class R:
            returncode = 1
            stdout = ""
            stderr = "token recusado"

        def runner(cmd, **kw):
            seen["cmd"], seen["env"] = cmd, kw["env"]
            return R()

        ok, msg = da.refresh_client("cli-a", Path("/tmp/base"), runner=runner)
        self.assertFalse(ok)
        self.assertIn("token recusado", msg)
        self.assertEqual(seen["env"]["TPA_PROJECT"], "cli-a")
        self.assertTrue(seen["cmd"][-1].endswith("fetch_metrics.py"))


class PassFourTest(unittest.TestCase):
    def test_redaction_covers_dict_and_json_forms(self):
        for text in ("{'app_secret': 'abc123def456ghi'}", '{"client_secret":"abc123def456ghi"}',
                     "appsecret_proof=abc123def456ghi", 'x {\\"access_token\\":\\"abc123def456ghi\\"}'):
            self.assertNotIn("abc123def456ghi", da._redact(text))

    def test_total_is_partial_when_a_client_has_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _make(Path(tmp), "default", "cpl", "BRL", 1000.0, {"spend": 1000, "leads": 50})
            b = _make(Path(tmp), "b", "cpl", "BRL", 500.0, {"spend": 500, "leads": 10})
            (b.dashboards / "paid-traffic-7d.json").unlink()
            rows = [da.collect_client("default", a, 7, now=NOW), da.collect_client("b", b, 7, now=NOW)]
            totals = da.build_totals(rows)
            self.assertEqual(totals["BRL"]["clientes_sem_dado"], 1)
            self.assertIn("parcial: 1 cliente(s) sem dado", da.render_text(rows, totals, 7))
            self.assertIn("parcial: 1 cliente(s) sem dado", da.render_html(rows, totals, 7, now=NOW))

    def test_boolean_value_is_not_counted_and_negative_metrics_are_errors(self):
        self.assertEqual(da._num(True), 0.0)
        with tempfile.TemporaryDirectory() as tmp:
            p = _make(Path(tmp), "default", "cpl", "BRL", 100.0, {"spend": 100, "leads": -20})
            row = da.collect_client("default", p, 7, now=NOW)
            self.assertIn("negativo", row["erro"])
            self.assertEqual(da.build_totals([row]), {})

    def test_failed_refresh_is_marked_and_exit_code_is_3(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            _make(Path(tmp), "default", "cpl", "BRL", 100.0, {"spend": 100, "leads": 10})
            old_base, old_refresh = tpa_paths.base_dir, da.refresh_client
            tpa_paths.base_dir = lambda: Path(tmp)
            da.refresh_client = lambda name, base, **k: (False, "token recusado")
            out, err = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = da.main(["--atualizar"])
            finally:
                tpa_paths.base_dir, da.refresh_client = old_base, old_refresh
            self.assertEqual(code, 3)
            self.assertIn("atualização falhou", out.getvalue())


class ServerHostTest(unittest.TestCase):
    def test_default_allowed_hosts_are_local_only(self):
        self.assertEqual(da._Handler.allowed_hosts, {"127.0.0.1", "localhost"})


if __name__ == "__main__":
    unittest.main()


class DashboardJsonInjectionTest(unittest.TestCase):
    def test_json_for_script_cannot_close_the_script_tag(self):
        import paid_traffic_dashboard as ptd
        out = ptd._json_for_script({"name": "</script><img src=x onerror=alert(1)> & co"})
        self.assertNotIn("<", out)
        self.assertNotIn(">", out)
        self.assertEqual(json.loads(out)["name"], "</script><img src=x onerror=alert(1)> & co")
