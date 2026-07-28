#!/usr/bin/env python3
"""
Setup 6 — Uninstall

Remove configs, LaunchAgents, dashboards e (opcional) skills do Setup 6.
Reverte phase_completed 6→5 em config.json.

Uso:
  python3 setup/setup_uninstall.py
"""
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

OPERACAO = Path.home() / ".operacao-ia"
CONFIG = OPERACAO / "config" / "config.json"
META_ENV = OPERACAO / "config" / "meta.env"
PERFIL = OPERACAO / "config" / "meta_perfil.json"
PROGRESS = OPERACAO / "config" / "setup6_progress.json"
META_SCRIPTS = OPERACAO / "scripts" / "meta"
DASH_DIR = OPERACAO / "dashboards"
LAUNCH = Path.home() / "Library" / "LaunchAgents"
SKILLS_HOME = Path.home() / ".claude" / "skills"

PLISTS = [
    "com.zxlab.meta-fetch.plist",
    "com.zxlab.meta-dashboard-server.plist",
]

SKILLS = [
    "agente-trafego-pago",
    "meta-campaign-launcher",
    "meta-creative-brief",
    "meta-metrics-fetcher",
    "meta-performance-analyzer",
    "meta-budget-optimizer",
]


def remove_path(p, label):
    if p.exists():
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        print(f"  ✓ {label}: {p}")
    else:
        print(f"  - {label}: já removido")


def unload_launchagents():
    if platform.system() != "Darwin":
        print("  - LaunchAgents (não-macOS, pulando)")
        return
    for name in PLISTS:
        dst = LAUNCH / name
        if dst.exists():
            subprocess.run(["launchctl", "unload", str(dst)], capture_output=True)
            dst.unlink()
            print(f"  ✓ LaunchAgent: {name}")
        else:
            print(f"  - LaunchAgent {name}: já removido")


def kill_dashboard_server():
    """Mata processo na porta 8888 se ativo."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", ":8888"], capture_output=True, text=True, timeout=5
        )
        pids = [p for p in result.stdout.strip().split("\n") if p]
        for pid in pids:
            try:
                subprocess.run(["kill", "-9", pid], capture_output=True)
                print(f"  ✓ Processo :8888 morto (pid {pid})")
            except Exception:
                pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def revert_phase():
    if not CONFIG.exists():
        print("  - config.json: não existe")
        return
    try:
        data = json.loads(CONFIG.read_text())
    except Exception as e:
        print(f"  ⚠️  config.json inválido: {e}")
        return
    if data.get("phase_completed") == 6:
        data["phase_completed"] = 5
        CONFIG.write_text(json.dumps(data, indent=2))
        print("  ✓ phase_completed: 6 → 5")
    else:
        print(f"  - phase_completed já é {data.get('phase_completed')}")


def read_demo_campaign_ids():
    """Lê IDs DEMO de progress.json ANTES do uninstall remover o arquivo."""
    if not PROGRESS.exists():
        return []
    try:
        return json.loads(PROGRESS.read_text()).get("demo_campaign_ids", []) or []
    except Exception:
        return []


def show_demo_campaigns(ids):
    if ids:
        print()
        print("⚠️  Setup criou campanhas DEMO (em PAUSED):")
        for cid in ids:
            print(f"     - {cid}")
        print("   Pause/exclua manualmente no Ads Manager se quiser limpar.")


def main():
    print("=" * 60)
    print("DESINSTALAR Setup 6 — Tráfego Pago Meta ADS")
    print("=" * 60)
    print()
    print("[A] Manter skills + remover só configs/launchagents (recomendado se vai reinstalar)")
    print("[B] Remover TUDO (skills, configs, launchagents, dashboards, scripts)")
    print("[C] Cancelar")
    print()
    try:
        choice = input("Escolha [A/B/C]: ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        choice = "C"

    if choice not in ("A", "B"):
        print("Cancelado.")
        return 0

    # Cache demo IDs ANTES de remover progress.json
    demo_ids = read_demo_campaign_ids()

    print()
    print("Removendo…")
    print()

    print("LaunchAgents:")
    unload_launchagents()
    kill_dashboard_server()

    print("\nConfigs:")
    remove_path(META_ENV, "meta.env")
    remove_path(PERFIL, "meta_perfil.json")
    remove_path(PROGRESS, "setup6_progress.json")

    print("\nScripts:")
    remove_path(META_SCRIPTS, "scripts/meta/")

    print("\nDashboards:")
    if DASH_DIR.exists():
        for f in DASH_DIR.glob("paid-traffic-*"):
            f.unlink()
            print(f"  ✓ {f.name}")
    else:
        print("  - dashboards/: não existe")

    if choice == "B":
        print("\nSkills:")
        for slug in SKILLS:
            remove_path(SKILLS_HOME / slug, f"skill {slug}")
    else:
        print("\nSkills: mantidas (escolha [A])")

    print("\nReverter fase:")
    revert_phase()

    show_demo_campaigns(demo_ids)

    print()
    print("✅ Uninstall completo.")
    if choice == "A":
        print("   Pra reinstalar: re-rode o setup do zero (INICIAR SETUP).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
