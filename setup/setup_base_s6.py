#!/usr/bin/env python3
"""
Setup 6 — Etapa 0: Diagnóstico da Base
Verifica pré-requisitos, cria estrutura de pastas, mostra plano das 10 etapas.
"""
import json
import platform
import shutil
import sys
from pathlib import Path

OPERACAO = Path.home() / ".operacao-ia"
CONFIG = OPERACAO / "config" / "config.json"

REQUIRED_DIRS = [
    OPERACAO / "config",
    OPERACAO / "scripts" / "meta",
    OPERACAO / "dashboards",
    OPERACAO / "leads",
    OPERACAO / "logs",
]

ETAPAS = [
    "E0  Boas-vindas + Diagnóstico",
    "E1  Conectar MCP oficial Meta (OAuth)",
    "E2  Questionário: Perfil de Campanhas",
    "E3  Instalar Skills + Agente Orquestrador",
    "E4  Primeira coleta de métricas",
    "E5  Dashboard local (localhost:8888)",
    "E6  Skill: Criar Campanha",
    "E7  Skill: Briefing Criativo",
    "E8  Skills: Analyzer + Budget Optimizer",
    "E9  LaunchAgents (fetch 3x/dia + server)",
    "E10 Auditoria técnica + Finalização",
]


def check_python():
    if sys.version_info < (3, 9):
        print(f"❌ Python 3.9+ requerido. Você tem {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")
    return True


def check_gh():
    if shutil.which("gh"):
        print("✅ gh CLI instalado")
        return True
    print("⚠️  gh CLI não encontrado (opcional, mas recomendado)")
    return True  # não bloqueia


def check_config():
    """Produto avulso: nao exige setups anteriores.

    Se o config base nao existir (comprador que nao veio do ZX Control),
    cria um minimo viavel em vez de bloquear a instalacao.
    """
    if not CONFIG.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"phase_completed": 0, "origem": "trafego-pago-automatizado"}, indent=2))
        print(f"✅ Config base criado em {CONFIG}")
        return True
    try:
        json.loads(CONFIG.read_text())
    except Exception:
        CONFIG.write_text(json.dumps({"phase_completed": 0, "origem": "trafego-pago-automatizado"}, indent=2))
        print("✅ Config base recriado (o anterior estava corrompido)")
        return True
    print("✅ Config base encontrado")
    return True


def create_dirs():
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    print(f"✅ Estrutura criada em {OPERACAO}/")


def show_plan():
    print("\n" + "=" * 60)
    print("PLANO DAS 10 ETAPAS — Setup 6 Tráfego Pago Meta ADS")
    print("=" * 60)
    for e in ETAPAS:
        print(f"  {e}")
    print("=" * 60)


def main():
    print(f"\n🔍 Diagnóstico inicial — {platform.system()} {platform.release()}\n")
    ok = all([check_python(), check_gh(), check_config()])
    if not ok:
        sys.exit(1)
    create_dirs()
    show_plan()
    print("\n✅ Etapa 0 concluída. Pronto para a Etapa 1 (Conectar MCP Meta).")


if __name__ == "__main__":
    main()
