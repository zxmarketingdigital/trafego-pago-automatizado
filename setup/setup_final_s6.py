#!/usr/bin/env python3
"""
Setup 6 — Etapa 10 (parte 2): Finalização
Marca phase_completed=max(atual, 6), reabre dashboard, mostra mensagem final.
"""
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tpa_paths  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_base_s6 import (ConfigBackupError, backup_config_copy, fase_ilegivel, minimo_recuperado,  # noqa: E402
                           parse_phase, write_config_atomic)

_P = tpa_paths.active_paths()
OPERACAO = _P.home
CONFIG = _P.shared_config  # phase_completed é compartilhado entre os projetos
PERFIL = _P.perfil
META_ENV = _P.meta_env
PORT = _P.port


def read_ad_account():
    if not META_ENV.exists():
        return "(não configurado)"
    try:
        linhas = tpa_paths.read_text_compat(META_ENV).splitlines()
    except OSError:
        return "(não consegui ler meta.env agora)"
    for line in linhas:
        if line.startswith("META_AD_ACCOUNT_ID="):
            return line.split("=", 1)[1].strip() or "(não configurado)"
    return "(não configurado)"


CURRENCY_SYMBOLS = {"BRL": "R$", "EUR": "€", "USD": "$", "GBP": "£"}


def fmt_target(k, currency="BRL"):
    currency = str(currency or "BRL").strip().upper()
    fmt, target = k.get("format"), k.get("target", "")
    if fmt == "currency":
        symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
        return f"{symbol}{target}"
    if fmt == "percent":
        return f"{target}%"
    return f"{target}"


def main():
    tpa_paths.announce(_P)
    if not PERFIL.exists():
        print("❌ meta_perfil.json não existe (rode E2)")
        sys.exit(1)
    # Valida o perfil ANTES de mexer na fase: perfil quebrado nao pode deixar phase_completed=6.
    try:
        perfil = json.loads(tpa_paths.read_text_compat(PERFIL))
        kpis = perfil["kpis"]
        if not isinstance(kpis, list) or not all(isinstance(k, dict) and "key" in k and "label" in k for k in kpis):
            raise ValueError("lista 'kpis' inválida")
    except Exception as e:
        print(f"❌ meta_perfil.json inválido ({e}) — rode a E2 de novo. A fase NÃO foi atualizada.")
        sys.exit(1)

    # Este setup não exige nenhum setup anterior: config.json ausente/corrompido é recriado.
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    cfg = None
    recuperado = None
    if CONFIG.exists():
        try:
            texto = tpa_paths.read_text_compat(CONFIG)
        except OSError as e:
            print(f"❌ Não consegui ler {CONFIG} ({e}). Feche programas que possam estar com ele aberto "
                  "e rode de novo. A fase NÃO foi atualizada.")
            sys.exit(1)
        try:
            cfg = json.loads(texto)
            if not isinstance(cfg, dict):
                raise ValueError("config.json não é um objeto JSON")
        except Exception:
            try:
                backup = backup_config_copy(CONFIG)
            except ConfigBackupError:
                sys.exit(1)  # mensagem ja impressa; config original intacto
            print(f"⚠️  config.json inválido — cópia guardada em {backup.name}")
            print(f"   As outras configurações dele (inclusive de outros projetos) estão nessa cópia: "
                  f"corrija o JSON dela e copie de volta para {CONFIG}.")
            recuperado = minimo_recuperado(texto)  # texto ja lido: nunca reler o .bak
            cfg = None
    if cfg is None:
        cfg = recuperado or {"phase_completed": 0, "origem": "trafego-pago-automatizado"}
    anterior = parse_phase(cfg.get("phase_completed", 0))
    # fase existia no texto corrompido mas nao foi lida: preserva o registro antigo do uninstall
    manter_registro = (recuperado is not None and recuperado.get("setup6") is not None
                       and fase_ilegivel(texto))
    if anterior < 6 and manter_registro:
        cfg["phase_completed"] = 6
    elif anterior < 6:  # nunca reduz um valor existente maior
        # guarda o valor ORIGINAL de agora (ex.: "week5" ou 0) para o uninstall restaurar
        # exatamente; sobrescreve registro antigo, que so vale enquanto a fase e 6.
        original = cfg.get("phase_completed", 0)
        if isinstance(original, bool) or not isinstance(original, (int, float, str)):
            # null/lista/objeto: registra a MESMA fase que parse_phase leu (null = 0), para o
            # uninstall restaurar o que foi considerado aqui e nunca inventar um 5
            original = int(anterior) if float(anterior).is_integer() else anterior
        cfg["setup6"] = {"phase_before": original}
        cfg["phase_completed"] = 6
    try:
        write_config_atomic(cfg, CONFIG)
    except OSError as e:
        print(f"❌ Não consegui gravar {CONFIG} ({e}). Feche programas que possam estar com o "
              "arquivo aberto (antivírus, editor) e rode de novo. A fase NÃO foi atualizada.")
        sys.exit(1)
    print(f"✅ phase_completed = {cfg['phase_completed']}")

    ad_account = read_ad_account()
    currency = perfil.get("currency") or "BRL"
    kpis_lista = ", ".join(str(k["key"]) for k in kpis)
    metas_resumo = " | ".join(f"{k['label']} {fmt_target(k, currency)}" for k in kpis)

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
