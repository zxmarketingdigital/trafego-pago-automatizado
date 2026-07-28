#!/usr/bin/env python3
"""
Setup 6 — Etapa 6 (Test): cria campanha DEMO em DRAFT.

Imprime instruções pro Claude invocar `meta-campaign-launcher` com template
DEMO pré-preenchido baseado em meta_perfil.json. Não cria diretamente —
o Claude executa via tool calls do MCP oficial Meta.

Salva flag em ~/.operacao-ia/config/setup6_progress.json quando completa.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

OPERACAO = Path.home() / ".operacao-ia"
PERFIL = OPERACAO / "config" / "meta_perfil.json"
META_ENV = OPERACAO / "config" / "meta.env"
PROGRESS = OPERACAO / "config" / "setup6_progress.json"


def read_env(key):
    if not META_ENV.exists():
        return ""
    for line in META_ENV.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def update_progress(key, value):
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if PROGRESS.exists():
        try:
            data = json.loads(PROGRESS.read_text())
        except Exception:
            data = {}
    data[key] = value
    PROGRESS.write_text(json.dumps(data, indent=2))


def main():
    if not PERFIL.exists():
        print("❌ meta_perfil.json não existe. Rode E2 (setup_perfil_campanhas.py).")
        return 1

    perfil = json.loads(PERFIL.read_text())
    objectives = perfil.get("objectives", [])
    primary_objective = objectives[0] if objectives else "LEAD_GENERATION"
    ad_account = perfil.get("ad_account_id") or read_env("META_AD_ACCOUNT_ID")
    today = datetime.now().strftime("%Y-%m-%d")

    print("🧪 Etapa 6 — Test Campaign Run")
    print("=" * 60)
    print()
    print("INSTRUÇÕES PRO CLAUDE:")
    print()
    print("Invoque a skill `meta-campaign-launcher` com este TEMPLATE DEMO:")
    print()
    print(f"  Nome:       [DEMO Setup6] {today}")
    print(f"  Objetivo:   {primary_objective}  (do perfil do aluno)")
    print(f"  Budget:     R$10/dia ABO  (mínimo Meta)")
    print(f"  Audiência:  BR 25-55 placeholder (interesse 'marketing digital')")
    print(f"  Pixel:      auto-detectado (lookup de /act_<id>/adspixels)")
    print(f"  Página FB:  auto-detectada (lookup de /me/businesses)")
    print(f"  Criativo:   peça URL ao aluno OU placeholder")
    print(f"  Status:     PAUSED (rascunho)")
    print(f"  Conta:      {ad_account}")
    print()
    print("Após criar:")
    print("  - Mostre IDs (campaign_id, adset_id, ad_id)")
    print("  - Instrua aluno revisar em https://business.facebook.com/adsmanager/")
    print("  - Após confirmação do aluno que viu, rode:")
    print()
    print("    python3 setup/setup_e6_test_campaign.py --mark-done <campaign_id>")
    print()
    print("=" * 60)
    return 0


def mark_done(campaign_id):
    update_progress("e6_test_completed", datetime.now().isoformat(timespec="seconds"))
    progress_data = {}
    if PROGRESS.exists():
        try:
            progress_data = json.loads(PROGRESS.read_text())
        except Exception:
            pass
    ids = progress_data.get("demo_campaign_ids", [])
    if campaign_id and campaign_id not in ids:
        ids.append(campaign_id)
    update_progress("demo_campaign_ids", ids)
    print(f"✅ E6 marcada como concluída. Campanha {campaign_id} salva em progress.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--mark-done":
        sys.exit(mark_done(sys.argv[2]))
    sys.exit(main())
