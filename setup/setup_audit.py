#!/usr/bin/env python3
"""
Setup 6 — Etapa 10 (parte 1): Auditoria técnica
12 checks de validação. Não corrige sozinho — reporta para o Claude
revisar e corrigir individualmente cada falha.
"""
import json
import platform
import socket
import subprocess
import sys
from pathlib import Path

OPERACAO = Path.home() / ".operacao-ia"
SKILLS = Path.home() / ".claude" / "skills"
LAUNCH = Path.home() / "Library" / "LaunchAgents"

CHECKS = []


def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:
        ok, msg = False, f"Exceção: {e}"
    CHECKS.append((name, ok, msg))


def c_perfil():
    p = OPERACAO / "config" / "meta_perfil.json"
    if not p.exists():
        return False, "meta_perfil.json não existe (rode E2)"
    try:
        d = json.loads(p.read_text())
        if not d.get("kpis") or not d.get("primary_kpi"):
            return False, "Perfil inválido"
        return True, f"{len(d['kpis'])} KPIs configurados, primário={d['primary_kpi']}"
    except Exception as e:
        return False, f"JSON corrompido: {e}"


def c_skills():
    expected = [
        "agente-trafego-pago", "meta-campaign-launcher", "meta-creative-brief",
        "meta-metrics-fetcher", "meta-performance-analyzer", "meta-budget-optimizer",
    ]
    missing = [s for s in expected if not (SKILLS / s / "SKILL.md").exists()]
    if missing:
        return False, f"Faltando: {', '.join(missing)}"
    return True, "6 skills instaladas"


def c_dashboards():
    d = OPERACAO / "dashboards"
    if not d.exists():
        return False, "Pasta não existe"
    jsons = sorted(d.glob("paid-traffic-*d.json"))
    if not jsons:
        return False, "Nenhum JSON gerado (rode E4)"
    return True, f"{len(jsons)} JSONs: {[f.name for f in jsons]}"


def c_dashboard_html():
    d = OPERACAO / "dashboards"
    htmls = sorted(d.glob("paid-traffic-dashboard-*d.html"))
    if not htmls:
        return False, "Nenhum HTML gerado (rode E5)"
    return True, f"{len(htmls)} HTMLs"


def c_fetch_script():
    p = OPERACAO / "scripts" / "meta" / "fetch_metrics.py"
    return (p.exists(), str(p) if p.exists() else "Não copiado")


def c_dashboard_script():
    p = OPERACAO / "scripts" / "meta" / "paid_traffic_dashboard.py"
    return (p.exists(), str(p) if p.exists() else "Não copiado")


def c_server_running():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", 8888))
        s.close()
        return True, "localhost:8888 respondendo"
    except Exception:
        return False, "Server não está rodando (E5/E9)"


def _fetch_skipped():
    """Retorna razão do skip (se aluno escolheu pular meta-fetch em E9) ou None."""
    p = OPERACAO / "config" / "setup6_progress.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("fetch_skipped_reason")
    except Exception:
        return None


def c_launchagents_files():
    if platform.system() != "Darwin":
        return True, "macOS-only — pulado"
    skip = _fetch_skipped()
    expected = ["com.zxlab.meta-dashboard-server.plist"]
    if not skip:
        expected.insert(0, "com.zxlab.meta-fetch.plist")
    missing = [n for n in expected if not (LAUNCH / n).exists()]
    if missing:
        return False, f"Faltando: {missing}"
    suffix = f" (fetch pulado: {skip})" if skip else ""
    return True, f"{len(expected)} plist{'s' if len(expected) > 1 else ''} instalado{'s' if len(expected) > 1 else ''}{suffix}"


def c_launchagents_loaded():
    if platform.system() != "Darwin":
        return True, "macOS-only — pulado"
    skip = _fetch_skipped()
    expected_count = 1 if skip else 2
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    count = sum(1 for l in result.stdout.splitlines() if "zxlab.meta" in l)
    if count < expected_count:
        return False, f"Esperava {expected_count} job(s) ativo(s), encontrou {count}"
    suffix = f" (fetch pulado: {skip})" if skip else ""
    return True, f"{count} job(s) ativo(s){suffix}"


def c_phase_completed():
    p = OPERACAO / "config" / "config.json"
    if not p.exists():
        return False, "config.json base não existe"
    try:
        cfg = json.loads(p.read_text())
        return cfg.get("phase_completed", 0) >= 5, f"phase_completed={cfg.get('phase_completed')}"
    except Exception as e:
        return False, f"Erro: {e}"


def c_meta_env():
    p = OPERACAO / "config" / "meta.env"
    if not p.exists():
        return False, "meta.env não criado (E1)"
    content = p.read_text()
    if "META_AD_ACCOUNT_ID=act_" in content and "act_XXXXXXXXX" not in content:
        return True, "META_AD_ACCOUNT_ID configurado"
    return False, "META_AD_ACCOUNT_ID ainda placeholder"


def c_python_version():
    return sys.version_info >= (3, 9), f"Python {sys.version_info.major}.{sys.version_info.minor}"


def main():
    print("\n🔍 Auditoria Técnica — Setup 6\n")

    check("Pré-requisito Setup 5",     c_phase_completed)
    check("Python 3.9+",                c_python_version)
    check("meta.env preenchido",        c_meta_env)
    check("Perfil de campanhas",        c_perfil)
    check("6 skills instaladas",        c_skills)
    check("fetch_metrics.py copiado",   c_fetch_script)
    check("dashboard generator copiado",c_dashboard_script)
    check("Dashboards JSON gerados",    c_dashboards)
    check("Dashboards HTML gerados",    c_dashboard_html)
    check("LaunchAgents instalados",    c_launchagents_files)
    check("LaunchAgents ativos",        c_launchagents_loaded)
    check("Server localhost:8888",      c_server_running)

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    total = len(CHECKS)

    for name, ok, msg in CHECKS:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name:35s} — {msg}")

    print(f"\n{passed}/{total} checks passaram\n")

    if passed < total:
        print("⚠️  Corrija os checks vermelhos antes de finalizar.")
        sys.exit(1)
    print("🎉 Tudo OK. Pronto para setup_final_s6.py")


if __name__ == "__main__":
    main()
