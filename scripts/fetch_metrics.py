#!/usr/bin/env python3
"""
fetch_metrics.py — coleta métricas Meta ADS adaptadas ao perfil do aluno.

Como funciona:
- Lê ~/.operacao-ia/config/meta_perfil.json (KPIs, metas, janelas, conta)
- Lê access token do MCP oficial Meta em ~/.claude.json
- Para cada janela, chama Meta Graph API v21.0 (level=ad) — header Authorization
- Faz 2ª query para campaigns (effective_status + budget atual)
- Armazena raw counters (spend, leads, purchases, msgs, impressions, clicks, ...)
- KPIs derivados (CPL, CPA, ROAS, CTR, CPM, CPC, custo/msg) calculados em cada nível
  a partir dos raws — agregação correta (sum/sum), nunca média ponderada de razões
- Aplica decide() por ad usando limiares do perfil
- Grava ~/.operacao-ia/dashboards/paid-traffic-{N}d.json

Modos:
  --check   : só valida config + token presente, não chama API
  (default) : roda fetch — exit code != 0 se qualquer janela falhar
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

OPERACAO = Path.home() / ".operacao-ia"
PERFIL = OPERACAO / "config" / "meta_perfil.json"
META_ENV = OPERACAO / "config" / "meta.env"
DASH_DIR = OPERACAO / "dashboards"
LOG = OPERACAO / "logs" / "meta-fetch.log"

GRAPH_BASE = "https://graph.facebook.com/v21.0"
BRT = timezone(timedelta(hours=-3))

# Mapeamento KPI → lista de action_types aceitos (variantes Meta).
# Soma todos os tipos da lista (ex: lead = sum(lead, onsite_lead, leadgen.other)).
ACTION_TYPES = {
    "leads": [
        "lead",
        "onsite_conversion.lead_grouped",
        "leadgen.other",
        "offsite_conversion.fb_pixel_lead",
    ],
    "purchases": [
        "purchase",
        "onsite_conversion.purchase",
        "offsite_conversion.fb_pixel_purchase",
        "omni_purchase",
    ],
    "messages": [
        "onsite_conversion.messaging_conversation_started_7d",
        "onsite_conversion.messaging_first_reply",
    ],
    "installs": [
        "mobile_app_install",
        "app_install",
    ],
}

PURCHASE_VALUE_TYPES = ACTION_TYPES["purchases"]


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(BRT).isoformat(timespec="seconds")
    line = f"[{ts}] {msg}\n"
    try:
        with LOG.open("a") as f:
            f.write(line)
    except Exception:
        pass


def read_env(key):
    if not META_ENV.exists():
        return ""
    for line in META_ENV.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def read_token():
    """Lê access_token de meta.env (fonte de verdade) ou env var."""
    return read_env("META_ACCESS_TOKEN") or os.environ.get("META_ACCESS_TOKEN") or None


def graph_get(path, params, token, *, page_url=None):
    """GET no Graph API com Authorization: Bearer (não na query string)."""
    headers = {
        "User-Agent": "zx-control-trafego-pago/0.1.1",
        "Authorization": f"Bearer {token}",
    }
    if page_url:
        url = page_url
        # Se URL paginada já carrega access_token na query (vinda do .next),
        # remove pra evitar leak duplicado/conflito.
        if "access_token=" in url:
            from urllib.parse import urlparse, urlencode as ue, parse_qsl, urlunparse
            u = urlparse(url)
            qs = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != "access_token"]
            url = urlunparse(u._replace(query=ue(qs)))
    else:
        url = f"{GRAPH_BASE}/{path.lstrip('/')}?{urlencode(params)}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Graph API {e.code}: {body[:300]}")


def get_action_count(actions, action_type_list):
    if not actions:
        return 0.0
    total = 0.0
    for a in actions:
        if a.get("action_type") in action_type_list:
            try:
                total += float(a.get("value", 0) or 0)
            except (ValueError, TypeError):
                pass
    return total


def fetch_insights(account_id, days, token):
    until = datetime.now(BRT).date()
    since = until - timedelta(days=days - 1)
    fields = ",".join([
        "ad_id", "ad_name", "adset_id", "adset_name",
        "campaign_id", "campaign_name", "objective",
        "spend", "impressions", "clicks", "reach", "frequency",
        "cpm", "ctr", "cpc",
        "actions", "action_values",
    ])
    params = {
        "level": "ad",
        "fields": fields,
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        "filtering": json.dumps([{"field": "ad.effective_status",
                                  "operator": "IN",
                                  "value": ["ACTIVE", "PAUSED"]}]),
        "limit": 500,
    }
    account = account_id if str(account_id).startswith("act_") else f"act_{account_id}"
    rows = []
    page = graph_get(f"{account}/insights", params, token)
    rows.extend(page.get("data", []))
    while page.get("paging", {}).get("next"):
        page = graph_get(None, None, token, page_url=page["paging"]["next"])
        rows.extend(page.get("data", []))
    return rows


def fetch_campaign_meta(account_id, token):
    """Pega effective_status + budget de cada campanha (necessário pro budget-optimizer)."""
    account = account_id if str(account_id).startswith("act_") else f"act_{account_id}"
    fields = "id,name,effective_status,daily_budget,lifetime_budget,bid_strategy,status"
    params = {"fields": fields, "limit": 500}
    out = {}
    page = graph_get(f"{account}/campaigns", params, token)
    for c in page.get("data", []):
        out[c["id"]] = c
    while page.get("paging", {}).get("next"):
        page = graph_get(None, None, token, page_url=page["paging"]["next"])
        for c in page.get("data", []):
            out[c["id"]] = c
    return out


def row_raws(row):
    """Extrai counters raw de uma linha de insight (ad)."""
    return {
        "spend": float(row.get("spend") or 0),
        "impressions": int(row.get("impressions") or 0),
        "clicks": int(row.get("clicks") or 0),
        "reach": int(row.get("reach") or 0),
        "leads": get_action_count(row.get("actions"), ACTION_TYPES["leads"]),
        "purchases": get_action_count(row.get("actions"), ACTION_TYPES["purchases"]),
        "purchase_value": get_action_count(row.get("action_values"), PURCHASE_VALUE_TYPES),
        "messages": get_action_count(row.get("actions"), ACTION_TYPES["messages"]),
        "installs": get_action_count(row.get("actions"), ACTION_TYPES["installs"]),
    }


def merge_raws(target, src):
    for k, v in src.items():
        target[k] = target.get(k, 0) + v


def calc_kpi(raws, kpi_key):
    spend = raws.get("spend", 0)
    impressions = raws.get("impressions", 0)
    clicks = raws.get("clicks", 0)

    if kpi_key == "cpl":
        leads = raws.get("leads", 0)
        return (spend / leads) if leads > 0 else None
    if kpi_key == "cpa":
        purchases = raws.get("purchases", 0)
        return (spend / purchases) if purchases > 0 else None
    if kpi_key == "roas":
        return (raws.get("purchase_value", 0) / spend) if spend > 0 else None
    if kpi_key == "cost_per_msg":
        msgs = raws.get("messages", 0)
        return (spend / msgs) if msgs > 0 else None
    if kpi_key == "cost_per_install":
        installs = raws.get("installs", 0)
        return (spend / installs) if installs > 0 else None
    if kpi_key == "cpm":
        return (spend / impressions * 1000) if impressions > 0 else None
    if kpi_key == "ctr":
        return (clicks / impressions * 100) if impressions > 0 else None
    if kpi_key == "cpc":
        return (spend / clicks) if clicks > 0 else None
    if kpi_key == "frequency":
        reach = raws.get("reach", 0)
        return (impressions / reach) if reach > 0 else None
    return None


def decide(value, kpi_meta, spend):
    target = kpi_meta.get("target") or 0
    if target <= 0:
        return "KEEP", "target inválido"
    scale_at = kpi_meta.get("scale_at", 0.8)
    kill_at = kpi_meta.get("kill_at", 1.5)
    better = kpi_meta.get("better", "lower")
    min_spend = max(target * 1.2, 30)

    if value is None:
        if spend >= target * 3:
            return "KILL", f"sem conversões após R${spend:.2f} de gasto"
        return "KEEP-amostra", "amostra insuficiente"

    if spend < min_spend:
        return "KEEP-amostra", f"spend R${spend:.2f} < min R${min_spend:.2f}"

    if better == "lower":
        if value <= target * scale_at:
            return "SCALE", f"{kpi_meta['key']} {value:.2f} ≤ {target*scale_at:.2f} ({(target-value)/target*100:.0f}% abaixo da meta)"
        if value > target * kill_at:
            return "KILL", f"{kpi_meta['key']} {value:.2f} > {target*kill_at:.2f} ({(value-target)/target*100:.0f}% acima da meta)"
        return "KEEP", f"{kpi_meta['key']} {value:.2f} dentro da banda"
    else:
        if value >= target * (2 - scale_at):
            return "SCALE", f"{kpi_meta['key']} {value:.2f} ≥ {target*(2-scale_at):.2f} (acima da meta)"
        if value < target * (2 - kill_at):
            return "KILL", f"{kpi_meta['key']} {value:.2f} < {target*(2-kill_at):.2f} (muito abaixo)"
        return "KEEP", f"{kpi_meta['key']} {value:.2f} dentro da banda"


def status_color(value, kpi_meta):
    if value is None:
        return "gray"
    target = kpi_meta.get("target") or 0
    if target <= 0:
        return "gray"
    better = kpi_meta.get("better", "lower")
    delta = (value - target) / target
    if better == "lower":
        if delta < -0.10: return "green"
        if delta <  0.10: return "yellow"
        return "red"
    else:
        if delta >  0.10: return "green"
        if delta > -0.10: return "yellow"
        return "red"


def aggregate(rows, perfil, campaign_meta):
    primary_kpi = perfil["primary_kpi"]
    kpi_meta_map = {k["key"]: k for k in perfil["kpis"]}
    primary_meta = kpi_meta_map[primary_kpi]

    by_camp = {}
    for row in rows:
        cid = row.get("campaign_id")
        asid = row.get("adset_id")
        raws = row_raws(row)

        ad_metrics = {k["key"]: calc_kpi(raws, k["key"]) for k in perfil["kpis"]}
        decide_v, decide_r = decide(ad_metrics.get(primary_kpi), primary_meta, raws["spend"])

        ad = {
            "ad_id": row.get("ad_id"),
            "ad_name": row.get("ad_name", ""),
            "raws": raws,
            "spend": raws["spend"],
            "metrics": ad_metrics,
            "decide": decide_v,
            "decide_reason": decide_r,
        }

        camp = by_camp.setdefault(cid, {
            "campaign_id": cid,
            "name": row.get("campaign_name", ""),
            "objective": row.get("objective", ""),
            "raws": {},
            "adsets": {},
        })
        merge_raws(camp["raws"], raws)

        adset = camp["adsets"].setdefault(asid, {
            "adset_id": asid,
            "name": row.get("adset_name", ""),
            "raws": {},
            "ads": [],
        })
        merge_raws(adset["raws"], raws)
        adset["ads"].append(ad)

    campaigns = []
    account_raws = {}
    for cid, camp in by_camp.items():
        merge_raws(account_raws, camp["raws"])
        meta = campaign_meta.get(cid, {})
        adset_list = []
        all_decisions = []
        for asid, adset in camp["adsets"].items():
            adset["spend"] = adset["raws"]["spend"]
            adset["metrics"] = {k["key"]: calc_kpi(adset["raws"], k["key"]) for k in perfil["kpis"]}
            adset_list.append(adset)
            all_decisions.extend(a["decide"] for a in adset["ads"])

        camp["spend"] = camp["raws"]["spend"]
        camp["metrics"] = {k["key"]: calc_kpi(camp["raws"], k["key"]) for k in perfil["kpis"]}
        # decide() agregado: pior decisão entre os ads
        if "KILL" in all_decisions:
            camp["decide"] = "KILL"
        elif "SCALE" in all_decisions:
            camp["decide"] = "SCALE"
        elif "KEEP" in all_decisions:
            camp["decide"] = "KEEP"
        else:
            camp["decide"] = "KEEP-amostra"
        camp["effective_status"] = meta.get("effective_status")
        camp["daily_budget"]    = int(meta.get("daily_budget") or 0) / 100 if meta.get("daily_budget") else None
        camp["lifetime_budget"] = int(meta.get("lifetime_budget") or 0) / 100 if meta.get("lifetime_budget") else None
        camp["bid_strategy"]    = meta.get("bid_strategy")
        camp["adsets"] = adset_list
        campaigns.append(camp)

    kpis_summary = {}
    for k in perfil["kpis"]:
        v = calc_kpi(account_raws, k["key"])
        target = k.get("target") or 0
        delta = ((v - target) / target * 100) if (v is not None and target > 0) else None
        kpis_summary[k["key"]] = {
            "value": (round(v, 4) if v is not None else None),
            "target": target,
            "delta_pct": (round(delta, 1) if delta is not None else None),
            "status": status_color(v, k),
        }

    return campaigns, kpis_summary, account_raws


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Só valida config")
    args = parser.parse_args()

    if not PERFIL.exists():
        print("❌ ~/.operacao-ia/config/meta_perfil.json não existe. Rode E3.")
        return 1

    perfil = json.loads(PERFIL.read_text())
    ad_account = perfil.get("ad_account_id") or read_env("META_AD_ACCOUNT_ID")
    if not ad_account or "XXXXX" in ad_account:
        print("❌ ad_account_id não configurado. Rode E2 (OAuth).")
        return 1

    token = read_token()
    if not token:
        meta_env_status = "existe" if META_ENV.exists() else "não existe"
        print("❌ Token Meta inválido ou ausente.")
        print()
        print("Diagnóstico:")
        print(f"  - meta.env: {meta_env_status} ({META_ENV})")
        print(f"  - META_ACCESS_TOKEN preenchido: não")
        print()
        print("Pra resolver, rode:")
        print("  python3 setup/setup_meta_oauth.py --renew")
        print()
        print("Ou gere token manual:")
        print("  1. Abra https://business.facebook.com/settings/system-users")
        print("  2. Selecione system user, clique 'Gerar token'")
        print("  3. Permissões: ads_management, ads_read, business_management")
        print("  4. Cole no terminal quando pedir.")
        return 1

    if args.check:
        print(f"✅ OK conta {ad_account}, {len(perfil['kpis'])} KPIs, janelas {perfil.get('windows', [])}")
        return 0

    DASH_DIR.mkdir(parents=True, exist_ok=True)
    windows = perfil.get("windows", [4, 7, 14, 30])
    log(f"START fetch account={ad_account} windows={windows}")

    # Fetch campaign metadata uma vez (effective_status + budget)
    try:
        campaign_meta = fetch_campaign_meta(ad_account, token)
    except Exception as e:
        print(f"❌ Falha ao listar campanhas (effective_status/budget): {e}")
        log(f"campaign_meta ERROR {e}")
        return 2

    failures = 0
    for days in windows:
        try:
            log(f"fetch window {days}d")
            rows = fetch_insights(ad_account, days, token)
            campaigns, kpis_summary, raws = aggregate(rows, perfil, campaign_meta)
            out = {
                "generated_at": datetime.now(BRT).isoformat(timespec="seconds"),
                "window_days": days,
                "ad_account_id": ad_account,
                "currency": "BRL",
                "perfil_kpis": [k["key"] for k in perfil["kpis"]],
                "primary_kpi": perfil["primary_kpi"],
                "kpis_summary": kpis_summary,
                "spend_total": round(raws.get("spend", 0), 2),
                "raws_total": raws,
                "campaigns": campaigns,
            }
            outfile = DASH_DIR / f"paid-traffic-{days}d.json"
            outfile.write_text(json.dumps(out, indent=2, ensure_ascii=False))
            print(f"✅ {outfile.name} — {len(rows)} ads, R${raws.get('spend', 0):.2f}")
            log(f"  -> {outfile.name} OK")
        except Exception as e:
            failures += 1
            print(f"❌ janela {days}d falhou: {e}")
            log(f"  -> ERROR {e}")

    log(f"END failures={failures}")
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
