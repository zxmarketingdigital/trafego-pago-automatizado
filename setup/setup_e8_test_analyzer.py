#!/usr/bin/env python3
"""
Setup 6 — Etapa 8 (Test): roda analyzer + budget-optimizer.

Verifica se há dados em paid-traffic-7d.json. Se sim, instrui Claude a
invocar `meta-performance-analyzer`. Se não há ads qualificados, mostra
mensagem orientativa (espere 24-72h pra acumular dados).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

OPERACAO = Path.home() / ".operacao-ia"
DASH = OPERACAO / "dashboards" / "paid-traffic-7d.json"
PROGRESS = OPERACAO / "config" / "setup6_progress.json"


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


def count_qualified_ads():
    if not DASH.exists():
        return 0, "dashboard 7d não existe"
    try:
        data = json.loads(DASH.read_text())
    except Exception as e:
        return 0, f"JSON inválido: {e}"
    qualified = 0
    for camp in data.get("campaigns", []):
        for adset in camp.get("adsets", []):
            for ad in adset.get("ads", []):
                # decide() != KEEP-amostra significa amostra suficiente
                if ad.get("decide") and ad["decide"] != "KEEP-amostra":
                    qualified += 1
    return qualified, "ok"


def main():
    print("🧪 Etapa 8 — Test Analyzer + Budget Optimizer")
    print("=" * 60)
    print()
    qualified, status = count_qualified_ads()
    print(f"Ads qualificados na janela 7d: {qualified} ({status})")
    print()

    if qualified == 0:
        print("⚠️  Sem dados suficientes pra rodar analyzer com decisões reais.")
        print()
        print("INSTRUÇÕES PRO CLAUDE:")
        print()
        print("Diga ao aluno:")
        print('  "Ainda não há ads com amostra suficiente (mín. 1.2× a meta de gasto).')
        print('   Isso é normal — campanhas novas demoram 24-72h pra acumular dados.')
        print('   Daqui a 1-3 dias rode `/meta-metrics-fetcher` e depois `meta-performance-analyzer`."')
        print()
        print("Pule budget-optimizer também (precisa de campanhas ativas com gasto).")
        print()
        update_progress("e8_test_completed", datetime.now().isoformat(timespec="seconds"))
        update_progress("e8_test_skipped", "no_qualified_ads")
    else:
        print("INSTRUÇÕES PRO CLAUDE:")
        print()
        print("1. Invoque `meta-performance-analyzer` na janela 7d")
        print("   → mostra top 3 SCALE / top 3 KILL / KEEP a monitorar")
        print()
        print("2. Se houver campanhas ACTIVE no dashboard, invoque `meta-budget-optimizer`")
        print("   com budget total = soma dos daily_budget atuais")
        print("   → mostra plano de realocação")
        print()
        print("3. Mostre os outputs ao aluno e pergunte se quer aplicar 1 mudança")
        print("   (via mcp__meta-official__ads_update_entity)")
        print()
        print("Após mostrar outputs:")
        print("  python3 setup/setup_e8_test_analyzer.py --mark-done")
        update_progress("e8_test_qualified_ads_count", qualified)

    print()
    print("=" * 60)
    return 0


def mark_done():
    update_progress("e8_test_completed", datetime.now().isoformat(timespec="seconds"))
    print("✅ E8 marcada como concluída.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--mark-done":
        sys.exit(mark_done())
    sys.exit(main())
