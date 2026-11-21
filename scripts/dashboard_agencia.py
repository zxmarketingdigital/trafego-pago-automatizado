#!/usr/bin/env python3
"""
dashboard_agencia.py — visão única de todos os clientes (projetos) do Tráfego Pago Automatizado.

Lê o que o coletor (fetch_metrics.py) já gravou em cada projeto
(<projeto>/dashboards/paid-traffic-{N}d.json) e mostra, por cliente e no total:
gasto, resultado, custo por resultado, CPA e ROAS. Não recalcula nada que o coletor
já calculou e não chama a API da Meta (a não ser com --atualizar, que roda o próprio
coletor de cada projeto, uma conta por vez, só leitura).

Uso:
  python3 scripts/dashboard_agencia.py                     resumo no terminal (janela 7d)
  python3 scripts/dashboard_agencia.py --janela 30         outra janela
  python3 scripts/dashboard_agencia.py --atualizar         roda o coletor de cada projeto antes
  python3 scripts/dashboard_agencia.py --saida html        grava <base>/dashboard-agencia/index.html
  python3 scripts/dashboard_agencia.py --servir            grava e abre em http://127.0.0.1:8887
  python3 scripts/dashboard_agencia.py --projetos a,b      só alguns projetos

Moedas diferentes nunca são somadas: o total é por moeda. Resultado e custo por resultado só
são somados entre clientes com o mesmo KPI primário (lead com lead, compra com compra).
Só biblioteca padrão.
"""
import argparse
import html
import http.server
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tpa_paths  # noqa: E402
from report_formatter import STALE_AFTER, _parse_generated_at, format_metric, format_number_br  # noqa: E402

DEFAULT_WINDOW = 7
AGENCY_PORT = 8887  # fora da faixa dos projetos (8888, 8889..8999); troque com --porta
OUT_SUBDIR = "dashboard-agencia"
API_STATUS_FILE = "api-status.json"


def _timeout_from_env(name, default):
    """Inteiro positivo vindo do ambiente. Valor ausente, inválido, zero ou negativo cai no padrão."""
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


FETCH_TIMEOUT = _timeout_from_env("ZX_TPA_AGENCIA_FETCH_TIMEOUT", 600)  # segundos por projeto

# KPI primário -> (campo em raws_total, rótulo do resultado)
RESULT_BY_KPI = {
    "cpl": ("leads", "leads"),
    "cpa": ("purchases", "compras"),
    "roas": ("purchases", "compras"),
    "cost_per_msg": ("messages", "conversas"),
    "cost_per_install": ("installs", "instalações"),
}


def _num(value):
    """Número finito ou 0.0 (só para exibição de bruto; contas usam _opt, que distingue ausente de zero)."""
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _opt(value):
    """Número finito, ou None quando a métrica está ausente/inválida (ausente nunca vira zero)."""
    if not _is_number(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _is_number(value):
    if isinstance(value, bool):
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _account(p):
    try:
        for line in tpa_paths.read_text_compat(p.meta_env).splitlines():
            if line.startswith("META_AD_ACCOUNT_ID="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def list_clients(base, only=None):
    """[(nome, Paths)] dos projetos que têm conta ou dado. O padrão vazio fica de fora."""
    out = []
    for name, p in tpa_paths.list_projects(base):
        if only and name not in only:
            continue
        has_data = p.meta_env.exists() or (p.dashboards.is_dir() and any(p.dashboards.glob("paid-traffic-*d.json")))
        if has_data or (only and name in only):
            out.append((name, p))
    return out


def collect_client(name, p, window, now=None):
    """Uma linha do painel, a partir do JSON do coletor. Nunca levanta: problema vira `erro`."""
    row = _blank_row(name, window)
    try:
        _fill_identity(row, p)
        _fill_row(row, p, window, now or datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - um cliente com JSON estranho não pode derrubar o painel
        row.update(erro="dado ilegível no coletor (%s)" % exc.__class__.__name__, gasto=None, moeda=None)
    return row


def _blank_row(name, window):
    return {
        "projeto": name,
        "conta": "",
        "janela": window,
        "erro": "",
        "moeda": None,
        "gasto": None,
        "kpi": None,
        "resultado_tipo": None,
        "resultado": None,
        "custo_por_resultado": None,
        "meta": None,
        "status": "gray",
        "compras": None,
        "cpa": None,
        "roas": None,
        "gerado_em": None,
        "defasado": False,
        "api_status": None,
        "atualizacao_falhou": False,
        "porta": None,
        "raws": {},
        "tem_compras": False,
        "tem_valor": False,
        "tem_resultado": False,
    }


def _fill_identity(row, p):
    row["conta"] = _account(p)
    try:
        row["porta"] = p.port
    except tpa_paths.TpaError:
        pass


def _fill_row(row, p, window, now):
    api_path = p.dashboards / API_STATUS_FILE
    api = _read_json(api_path)
    if api:
        status = api.get("status")
        row["api_status"] = status if isinstance(status, str) else None
    elif api_path.exists():
        row["api_status"] = "erro"  # existe mas está ilegível: não pode parecer "checagem nunca rodou"

    source = p.dashboards / ("paid-traffic-%dd.json" % window)
    data = _read_json(source)
    if data is None:
        row["erro"] = "sem coleta na janela de %d dias (%s). Rode o coletor deste projeto." % (window, source.name)
        return

    raws = data.get("raws_total")
    raws = raws if isinstance(raws, dict) else {}
    # Gasto ausente nunca vira zero: sem spend_total nem raws.spend a linha fica fora dos totais.
    spend_raw = data.get("spend_total")
    if spend_raw is None:
        spend_raw = raws.get("spend")
    currency = data.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        row["erro"] = "moeda não informada no coletor: reexecute o coletor deste projeto"
        return
    if spend_raw is None or not _is_number(spend_raw):
        row["erro"] = "gasto não informado no coletor: reexecute o coletor deste projeto"
        return
    spend = float(spend_raw)
    if not math.isfinite(spend) or spend < 0:
        row["erro"] = "gasto inválido no coletor: reexecute o coletor deste projeto"
        return
    kpi = data.get("primary_kpi")
    summaries = data.get("kpis_summary")
    summary = (summaries.get(kpi) if isinstance(summaries, dict) else None)
    summary = summary if isinstance(summary, dict) else {}
    field, label = RESULT_BY_KPI.get(kpi, (None, None))
    purchases = _opt(raws.get("purchases"))
    result = _opt(raws.get(field)) if field else None
    value = _opt(raws.get("purchase_value"))
    if any(x is not None and x < 0 for x in (purchases, result, value)):
        row["erro"] = "resultado, compras ou valor negativo no coletor: reexecute o coletor deste projeto"
        return

    row.update(
        moeda=currency.strip().upper(),
        gasto=spend,
        kpi=kpi,
        resultado_tipo=label,
        resultado=result,
        custo_por_resultado=(spend / result) if result is not None and result > 0 else None,
        meta=summary.get("target"),
        status=str(summary.get("status") or "gray"),
        compras=purchases,
        cpa=(spend / purchases) if purchases is not None and purchases > 0 else None,
        roas=(value / spend) if value is not None and spend > 0 and value > 0 else None,
        gerado_em=str(data.get("generated_at") or "")[:40] or None,
        raws={k: _num(v) for k, v in raws.items()},
        # Métrica ausente não é zero: só entra no CPA/ROAS do total quem de fato mede compras/valor.
        tem_compras=purchases is not None,
        tem_valor=value is not None,
        tem_resultado=result is not None,
    )
    try:
        generated = _parse_generated_at(data.get("generated_at"))
    except (ValueError, TypeError, AttributeError):
        generated = None
    row["defasado"] = generated is None or (now - generated.astimezone(timezone.utc)) > STALE_AFTER


def build_totals(rows):
    """Totais por moeda e, dentro dela, por tipo de resultado (KPI primário).
    Nunca soma moedas nem tipos de resultado diferentes."""
    totals = {}
    sem_dado = sum(1 for r in rows if r["erro"] or r["gasto"] is None)  # moeda deles é desconhecida: vale para todas
    for r in rows:
        if r["erro"] or r["gasto"] is None:
            continue
        cur = totals.setdefault(r["moeda"], {"gasto": 0.0, "clientes": 0, "grupos": {}, "clientes_sem_dado": sem_dado})
        cur["gasto"] += r["gasto"]
        cur["clientes"] += 1
        key = r["kpi"] if r["resultado_tipo"] else "outros"
        g = cur["grupos"].setdefault(
            key,
            {"tipo": r["resultado_tipo"], "gasto": 0.0, "resultado": 0.0, "valor": 0.0, "compras": 0.0, "clientes": 0,
             "gasto_compras": 0.0, "gasto_valor": 0.0, "clientes_compras": 0, "clientes_valor": 0,
             "gasto_resultado": 0.0, "clientes_resultado": 0},
        )
        g["gasto"] += r["gasto"]
        g["clientes"] += 1
        if r.get("tem_compras"):
            g["gasto_compras"] += r["gasto"]
            g["clientes_compras"] += 1
        if r.get("tem_valor"):
            g["gasto_valor"] += r["gasto"]
            g["clientes_valor"] += 1
        if r["resultado_tipo"] and r.get("tem_resultado"):
            g["resultado"] += r["resultado"]
            g["gasto_resultado"] += r["gasto"]
            g["clientes_resultado"] += 1
        g["valor"] += r["raws"].get("purchase_value", 0.0)
        g["compras"] += r["compras"] or 0.0
    for cur in totals.values():
        for g in cur["grupos"].values():
            g["custo_por_resultado"] = (
                g["gasto_resultado"] / g["resultado"] if g["tipo"] and g["resultado"] > 0 else None)
            g["custo_parcial"] = g["custo_por_resultado"] is not None and g["clientes_resultado"] < g["clientes"]
            # CPA e ROAS do total só sobre o gasto de quem mede compras/valor (nunca diluído por quem não mede).
            g["cpa"] = (g["gasto_compras"] / g["compras"]) if g["compras"] > 0 and g["gasto_compras"] > 0 else None
            g["roas"] = (g["valor"] / g["gasto_valor"]) if g["gasto_valor"] > 0 and g["valor"] > 0 else None
            g["cpa_parcial"] = g["cpa"] is not None and g["clientes_compras"] < g["clientes"]
            g["roas_parcial"] = g["roas"] is not None and g["clientes_valor"] < g["clientes"]
    return totals


# ---------------------------------------------------------------- atualizar (roda o coletor existente)
_SECRET_RE = re.compile(
    r"(access_token=|Bearer\s+|(?:token|client_secret|app_secret|appsecret_proof|secret)(?:\\?[\"'])?\s*[:=]\s*(?:\\?[\"'])?)"
    r"[^\s&\"'<>,}]{8,}", re.I)


def _redact(text):
    """Tira tokens de qualquer texto que vá para o terminal."""
    return _SECRET_RE.sub(lambda m: m.group(1) + "***", text)


def refresh_client(name, base, runner=subprocess.run, repo_scripts=None):
    """Roda o coletor deste projeto (fetch_metrics.py, só leitura). Devolve (ok, mensagem)."""
    script = Path(repo_scripts or Path(__file__).resolve().parent) / "fetch_metrics.py"
    env = dict(os.environ)
    env["TPA_PROJECT"] = name
    env["OPERACAO_IA_HOME"] = str(base)
    t0 = time.monotonic()
    try:
        res = runner([sys.executable, str(script)], env=env, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=FETCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "coletor passou de %ds (ZX_TPA_AGENCIA_FETCH_TIMEOUT)" % FETCH_TIMEOUT
    except OSError as exc:
        return False, "não consegui rodar o coletor (%s)" % exc
    took = time.monotonic() - t0
    if res.returncode != 0:
        tail = _redact(" ".join(((res.stdout or "") + " " + (res.stderr or "")).split()))[-200:]
        return False, "coletor saiu com código %d em %.0fs: %s" % (res.returncode, took, tail)
    return True, "coletado em %.0fs (teto %ds)" % (took, FETCH_TIMEOUT)


# ---------------------------------------------------------------- saída
API_ICON = {"ok": "✅", "atencao": "🟡", "critico": "🔴", "erro": "⚠️", "nao_verificado": "⚪"}


def _money(value, cur):
    return format_metric(value, "currency", cur) if value is not None else "—"


def _count(value):
    return format_number_br(value, 0) if value is not None else "—"


def _roas(value):
    return ("%sx" % format_number_br(value, 2)) if value is not None else "—"


def _result_cell(r):
    if r["erro"] or r["resultado_tipo"] is None or r["resultado"] is None:
        return "—"
    return "%s %s" % (_count(r["resultado"]), r["resultado_tipo"])


def _no_data(t):
    n = t.get("clientes_sem_dado") or 0
    return " (parcial: %d cliente(s) sem dado nesta janela ficaram de fora)" % n if n else ""


def _partial(have, total):
    return " (parcial: %d de %d clientes medem)" % (have, total)


def render_text(rows, totals, window):
    lines = ["PAINEL DE CLIENTES — janela de %d dias — %d projeto(s)" % (window, len(rows)), ""]
    head = "%-16s %-14s %-24s %-14s %-12s %-8s %s" % ("CLIENTE", "GASTO", "RESULTADO", "CUSTO/RESULT.", "CPA", "ROAS", "AVISOS")
    lines.append(head)
    for r in rows:
        if r["erro"]:
            extra = " | API Meta: %s" % r["api_status"] if r["api_status"] in ("atencao", "critico", "erro") else ""
            lines.append("%-16s %s%s" % (r["projeto"], r["erro"], extra))
            continue
        notes = []
        if r["defasado"]:
            notes.append("dado defasado (+26h)")
        if r["atualizacao_falhou"]:
            notes.append("atualização falhou (dado de %s)" % (r["gerado_em"] or "data desconhecida"))
        if r["api_status"] in ("atencao", "critico", "erro"):
            notes.append("API Meta: %s" % r["api_status"])
        lines.append("%-16s %-14s %-24s %-14s %-12s %-8s %s" % (
            r["projeto"], _money(r["gasto"], r["moeda"]), _result_cell(r),
            _money(r["custo_por_resultado"], r["moeda"]), _money(r["cpa"], r["moeda"]),
            _roas(r["roas"]), "; ".join(notes)))
    lines.append("")
    if not totals:
        lines.append("Nenhum cliente com dados nesta janela.")
    for cur, t in sorted(totals.items()):
        lines.append("TOTAL em %s — gasto %s (%d cliente(s))%s" % (cur, _money(t["gasto"], cur), t["clientes"], _no_data(t)))
        for g in t["grupos"].values():
            nome = g["tipo"] or "sem resultado direto (alcance/tráfego)"
            part = "  · %s: gasto %s" % (nome, _money(g["gasto"], cur))
            if g["tipo"]:
                part += " | %s %s | custo/resultado %s%s" % (
                    _count(g["resultado"]), g["tipo"], _money(g["custo_por_resultado"], cur),
                    _partial(g["clientes_resultado"], g["clientes"]) if g["custo_parcial"] else "")
            if g["cpa"] is not None:
                part += " | CPA %s%s" % (_money(g["cpa"], cur), _partial(g["clientes_compras"], g["clientes"]) if g["cpa_parcial"] else "")
            if g["roas"] is not None:
                part += " | ROAS %s%s" % (_roas(g["roas"]), _partial(g["clientes_valor"], g["clientes"]) if g["roas_parcial"] else "")
            lines.append(part)
    return "\n".join(lines)


CSS = """
:root{--bg:#0a0a0a;--card:#141414;--line:#2a2a2a;--text:#e5e5e5;--muted:#9ca3af;--accent:#fbbf24;--green:#22c55e;--yellow:#eab308;--red:#ef4444}
*{box-sizing:border-box}body{margin:0;padding:24px;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,sans-serif}
h1{color:var(--accent);font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px;color:var(--accent)}
.meta{color:var(--muted);font-size:13px;margin-bottom:18px}.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;background:var(--card);font-size:14px}th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase}td.n{text-align:right;font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:var(--muted)}
.green{background:var(--green)}.yellow{background:var(--yellow)}.red{background:var(--red)}.warn{color:var(--yellow)}.err{color:var(--red)}
a{color:var(--accent)}tr.total td{font-weight:700}
@media(max-width:640px){body{padding:14px}}
"""


def render_html(rows, totals, window, now=None):
    esc = lambda v: html.escape(str(v), quote=True)  # noqa: E731
    now = now or datetime.now()
    out = ["<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">",
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
           "<title>Painel de clientes — Tráfego Pago</title><style>%s</style></head><body>" % CSS,
           "<h1>Painel de clientes — Tráfego Pago Meta ADS</h1>",
           "<div class=\"meta\">Janela de %d dias · %d projeto(s) · gerado em %s</div>" % (
               window, len(rows), esc(now.strftime("%d/%m/%Y %H:%M"))),
           "<div class=\"wrap\"><table><tr><th>Cliente</th><th>Conta</th><th>Gasto</th><th>Resultado</th>"
           "<th>Custo/resultado</th><th>CPA</th><th>ROAS</th><th>Atualizado</th><th>API Meta</th></tr>"]
    for r in rows:
        link = esc(r["projeto"])
        if r["porta"]:
            link = '<a href="http://localhost:%d/paid-traffic-dashboard-%dd.html">%s</a>' % (r["porta"], window, esc(r["projeto"]))
        if r["erro"]:
            out.append("<tr><td>%s</td><td>%s</td><td colspan=\"7\" class=\"err\">%s</td></tr>" % (
                link, esc(r["conta"] or "—"),
                esc(r["erro"] + ((" | API Meta: " + r["api_status"]) if r["api_status"] in API_ICON and r["api_status"] != "ok" else ""))))
            continue
        cur = r["moeda"]
        gen = esc(r["gerado_em"] or "—")
        if r["defasado"]:
            gen += ' <span class="warn">defasado (+26h)</span>'
        if r["atualizacao_falhou"]:
            gen += ' <span class="err">atualização falhou</span>'
        api = ("%s %s" % (API_ICON[r["api_status"]], esc(r["api_status"]))) if r["api_status"] in API_ICON else "—"
        out.append(
            "<tr><td><span class=\"dot %s\"></span>%s</td><td>%s</td><td class=\"n\">%s</td><td>%s</td>"
            "<td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(r["status"] if r["status"] in ("green", "yellow", "red") else ""), link,
                esc(r["conta"] or "—"), esc(_money(r["gasto"], cur)), esc(_result_cell(r)),
                esc(_money(r["custo_por_resultado"], cur)), esc(_money(r["cpa"], cur)),
                esc(_roas(r["roas"])), gen, api))
    out.append("</table></div>")
    if not totals:
        out.append("<p class=\"meta\">Nenhum cliente com dados nesta janela.</p>")
    for cur, t in sorted(totals.items()):
        out.append("<h2>Total em %s — gasto %s (%d cliente(s))%s</h2><div class=\"wrap\"><table>"
                   "<tr><th>Tipo de resultado</th><th>Gasto</th><th>Resultado</th><th>Custo/resultado</th><th>CPA</th><th>ROAS</th></tr>" % (
                       esc(cur), esc(_money(t["gasto"], cur)), t["clientes"], esc(_no_data(t))))
        for g in t["grupos"].values():
            out.append("<tr class=\"total\"><td>%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td><td class=\"n\">%s</td></tr>" % (
                esc(g["tipo"] or "sem resultado direto"), esc(_money(g["gasto"], cur)),
                esc("%s %s" % (_count(g["resultado"]), g["tipo"]) if g["tipo"] else "—"),
                esc(_money(g["custo_por_resultado"], cur) + (_partial(g["clientes_resultado"], g["clientes"]) if g.get("custo_parcial") else "")),
                esc(_money(g["cpa"], cur) + (_partial(g["clientes_compras"], g["clientes"]) if g.get("cpa_parcial") else "")),
                esc(_roas(g["roas"]) + (_partial(g["clientes_valor"], g["clientes"]) if g.get("roas_parcial") else ""))))
        out.append("</table></div>")
    out.append("<p class=\"meta\">Moedas e tipos de resultado diferentes nunca são somados. "
               "Dados do coletor de cada projeto; nada é recalculado aqui.</p></body></html>")
    return "".join(out)


def write_html(base, rows, totals, window):
    out_dir = Path(base) / OUT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "index.html"
    tpa_paths._atomic_write(target, render_html(rows, totals, window))
    return target


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Só atende Host local (e os domínios liberados com --host-permitido): evita DNS rebinding."""

    allowed_hosts = {"127.0.0.1", "localhost"}

    def parse_request(self):
        if not super().parse_request():
            return False
        if (self.headers.get("Host") or "").split(":")[0].lower() not in self.allowed_hosts:
            self.send_error(403)
            return False
        return True


PROTECTION_REFUSAL = (
    "❌ --host-permitido libera o painel (gasto e contas dos seus clientes) para o endereço: %s\n"
    "   Este servidor NÃO tem login. Só use atrás de Cloudflare Access, Caddy com senha ou túnel SSH\n"
    "   (veja docs/vps.md). Com a proteção já ativa e testada numa janela anônima, repita o comando\n"
    "   acrescentando --protegido-por-acesso."
)


def serve(directory, port, extra_hosts=()):
    handler = type("AgencyHandler", (_Handler,), {"allowed_hosts": {"127.0.0.1", "localhost"} | {h.lower() for h in extra_hosts}})
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), partial(handler, directory=str(directory))) as httpd:
        print("Painel em http://127.0.0.1:%d (Ctrl+C para parar)" % port)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Painel consolidado de todos os clientes (projetos)")
    parser.add_argument("--janela", type=int, default=DEFAULT_WINDOW, help="janela em dias (padrão %d)" % DEFAULT_WINDOW)
    parser.add_argument("--projetos", help="lista separada por vírgula (padrão: todos)")
    parser.add_argument("--atualizar", action="store_true", help="roda o coletor de cada projeto antes (só leitura)")
    parser.add_argument("--saida", choices=("texto", "json", "html"), default="texto")
    parser.add_argument("--servir", action="store_true", help="grava o HTML e serve em 127.0.0.1")
    parser.add_argument("--porta", type=int, default=AGENCY_PORT)
    parser.add_argument("--host-permitido", action="append", default=[], help="domínio extra aceito (túnel/proxy); repita se preciso")
    parser.add_argument("--protegido-por-acesso", action="store_true",
                        help="confirma que o endereço de --host-permitido está atrás de login (Cloudflare Access, Caddy com senha...)")
    args = parser.parse_args(argv)
    if args.janela < 1:
        parser.error("--janela precisa ser maior que zero")
    # O navegador manda só o nome (sem esquema, porta ou caminho): normaliza o que o aluno digitar.
    args.host_permitido = [re.sub(r"^[a-z]+://", "", h.strip().lower()).split("/")[0].split(":")[0]
                           for h in args.host_permitido if h.strip()]
    if args.host_permitido and not args.protegido_por_acesso:
        print(PROTECTION_REFUSAL % ", ".join(args.host_permitido), file=sys.stderr)
        return 2

    base = tpa_paths.base_dir()
    only = {x.strip() for x in args.projetos.split(",") if x.strip()} if args.projetos else None
    clients = list_clients(base, only)
    if only:
        missing = only - {n for n, _p in clients}
        if missing:
            print("❌ Projeto(s) inexistente(s): %s. Veja: python3 setup/tpa_projeto.py listar" % ", ".join(sorted(missing)), file=sys.stderr)
            return 1
    if not clients:
        print("Nenhum projeto com conta ou dado em %s." % base)
        return 1

    failed = set()
    if args.atualizar:
        for name, _p in clients:
            ok, msg = refresh_client(name, base)
            print("%s %s: %s" % ("✅" if ok else "⚠️ ", name, msg), file=sys.stderr)
            if not ok:
                failed.add(name)

    rows = [collect_client(n, p, args.janela) for n, p in clients]
    for r in rows:
        r["atualizacao_falhou"] = r["projeto"] in failed
    totals = build_totals(rows)

    if args.servir:
        target = write_html(base, rows, totals, args.janela)
        serve(target.parent, args.porta, args.host_permitido)
        return 3 if failed else 0
    if args.saida == "html":
        target = write_html(base, rows, totals, args.janela)
        print("✅ Painel gravado em %s" % target)
    elif args.saida == "json":
        print(json.dumps({"janela": args.janela, "clientes": rows, "totais": totals}, indent=2, ensure_ascii=False))
    else:
        print(render_text(rows, totals, args.janela))
    return 3 if failed else 0  # automação (cron) precisa saber que os números NÃO são de agora


if __name__ == "__main__":
    sys.exit(main())
