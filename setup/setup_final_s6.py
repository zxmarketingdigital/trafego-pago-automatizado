#!/usr/bin/env python3
"""
Setup 6 — Etapa 10 (parte 2): Finalização
Marca phase_completed=6, reabre dashboard, mostra mensagem final.
"""
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tpa_paths  # noqa: E402

_P = tpa_paths.active_paths()
OPERACAO = _P.home
CONFIG = _P.shared_config  # phase_completed é compartilhado entre os projetos
PERFIL = _P.perfil
META_ENV = _P.meta_env
PORT = _P.port


def read_ad_account():
    if not META_ENV.exists():
        return "(não configurado)"
    for line in tpa_paths.read_text_compat(META_ENV).splitlines():
        if line.startswith("META_AD_ACCOUNT_ID="):
            return line.split("=", 1)[1].strip() or "(não configurado)"
    return "(não configurado)"


CURRENCY_SYMBOLS = {"BRL": "R$", "EUR": "€", "USD": "$", "GBP": "£"}


def fmt_target(k, currency="BRL"):
    currency = str(currency or "BRL").strip().upper()
    if k["format"] == "currency":
        symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
        return f"{symbol}{k['target']}"
    if k["format"] == "percent":
        return f"{k['target']}%"
    return f"{k['target']}"


def main():
    tpa_paths.announce(_P)
    if not CONFIG.exists():
        print("❌ config.json não existe")
        sys.exit(1)
    if not PERFIL.exists():
        print("❌ meta_perfil.json não existe (rode E2)")
        sys.exit(1)

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    cfg["phase_completed"] = max(cfg.get("phase_completed", 0), 6)
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ phase_completed = {cfg['phase_completed']}")

    perfil = json.loads(PERFIL.read_text(encoding="utf-8"))
    ad_account = read_ad_account()
    currency = perfil.get("currency") or "BRL"
    kpis_lista = ", ".join(k["key"] for k in perfil["kpis"])
    metas_resumo = " | ".join(f"{k['label']} {fmt_target(k, currency)}" for k in perfil["kpis"])

    url = f"http://localhost:{PORT}/paid-traffic-dashboard-7d.html"
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print(f"""
Setup 6 concluido!

O que voce tem agora:
- MCP oficial Meta conectado a conta {ad_account}
- 6 skills instaladas (5 especialistas + 1 agente orquestrador)
- Dashboard rodando em http://localhost:{PORT} (atualiza 8h/13h/19h)
- Projeto: {_P.name} ({_P.home})
- Estrategia decide() ativa nos KPIs: {kpis_lista}
- Metas configuradas: {metas_resumo}

Comandos do dia a dia:
/agente-trafego-pago        menu completo
/meta-campaign-launcher     criar nova campanha
/meta-creative-brief        gerar briefing
/meta-metrics-fetcher       atualizar dashboard agora
/meta-performance-analyzer  analise da semana
/meta-budget-optimizer      plano de realocacao

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Voce acabou de plugar trafego pago direto no Claude Code.
Conheca o ZX Control completo — mentoria semanal + todos os setups:
👉 https://zxlab.com.br/mission-control

Nos vemos no proximo setup!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


if __name__ == "__main__":
    main()
